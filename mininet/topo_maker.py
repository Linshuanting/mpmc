from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from ssh_connect import sshd
import json
import argparse
import os

file_folder = "/home/user/mpmc_implementation/mininet"

class TopologyMaker(Topo):
    def __init__(self, topology_data):
        super(TopologyMaker, self).__init__()
        self.myhosts = []
        self.myswitches = []
        self.mynodes = None
        self.mylinks = None
        self.host_ipv6 = {}
        self.ssh_sw = None

        # 讀取拓撲
        self.mynodes = topology_data["nodes"]
        self.mylinks = topology_data["links"]
        self.set_nodes(self.mynodes)

        self.create_topology()

    def set_nodes(self, nodes):
        """ 根據節點名稱將它們分類為 Host 或 Switch """
        for node in nodes:
            if node["name"].startswith('h'):
                self.myhosts.append(node["name"])
                if "ipv6" in node:
                    self.host_ipv6[node["name"]] = node["ipv6"]  # 儲存 IPv6 地址
            elif node["name"].startswith('s'):
                self.myswitches.append(node["name"])
    
    def create_topology(self, **kwargs):
        """ 根據讀取的 JSON 拓撲建立 Mininet 拓撲 """
        nodes = {}

        # 創建主機，並配置 MAC 和 IPv6
        for host in self.myhosts:
            host_id = int(host[1:])  # 提取 hX 的數字
            mac = f"00:00:00:00:00:{host_id:02d}"
            nodes[host] = self.addHost(host, mac=mac, ip=None)  # 先不設 IPv4
            # nodes[host] = self.addHost(host, mac=mac)  # 設定 IPv4

        # 創建交換機
        for sw in self.myswitches:
            nodes[sw] = self.addSwitch(sw, cls=OVSSwitch, protocols="OpenFlow15")

        # 建立鏈接
        for info in self.mylinks:
            src, dst = info["link"].split("-")
            if "bw" in info:
                bw = info["bw"]
                self.addLink(nodes[src], nodes[dst], bw=bw, max_queue_size=1000)
            else:
                self.addLink(nodes[src], nodes[dst])

def start_netfilterqueue(net):

    for host in net.hosts:

        host.cmd("killall iperf")
        host.cmd("ip6tables -F OUTPUT")

        print(f"Start NetFilterQueue on {host}")
        print(f"Start Iperf Server in each host:{host}")

        for i in range(5001, 5016, 1):
            host.cmd(f"ip6tables -A OUTPUT -p udp --dport {i} -j NFQUEUE --queue-num 1")
            # host.cmd(f"ip6tables -t mangle -A POSTROUTING -p udp -j CHECKSUM --checksum-fill")
            # host.cmd(f"ip6tables -A OUTPUT -p udp --dport {i} -j NFQUEUE --queue-balance 0:3")
            # host.cmd(f"nohup iperf -s -u -V -p {i} > /dev/null 2>&1 &")

        # host.cmd(f"setsid python3 /home/user/mininet/custom/modify_flabel.py > /dev/null 2>&1 &")
        host.cmd(f"setsid python3 {file_folder}/modify_flabel_one_iperf.py > /dev/null 2>&1 &")
        # host.cmd(f"setsid python3 {file_folder}/modify_flabel_test.py > /dev/null 2>&1 &")
        # host.cmd(f"setsid python3 {file_folder}/modify_flabel_multithread.py > /dev/null 2>&1 &")

def start_bpf(net):
    for host in net.hosts:
        print(f"Start BPF filter in each host:{host}")

        # 使用 bpffs 不要使用 bpf，不然 mkdir 不會成功
        host.cmd(f"mount bpffs -t bpf /sys/fs/bpf")
        host.cmd(f"mkdir -p /sys/fs/bpf/tc")

        host.cmd(f"tc qdisc add dev {host.defaultIntf()} clsact")
        host.cmd(f"tc filter add dev {host.defaultIntf()} ingress bpf da obj {file_folder}/eBPF/tree_label_kern.o sec classifier")

        host.cmd(f"python {file_folder}/eBPF/initial_tree_state.py")

def clear_netfilterqueue(net):
    
    for host in net.hosts:
        host.cmd("killall iperf")
        host.cmd("ip6tables -F OUTPUT")
        host.cmd("ip6tables -t mangle -F POSTROUTING")

def create_nftable(net):

    table_name = "myfilter"
    chain_name = "prerouting"

    for host in net.hosts:
        host.cmd(f"nft add table ip6 {table_name}")
        # mynat 是 nftable name
        # prerouting 是 chain
        host.cmd(
            f"nft add chain ip6 {table_name} {chain_name} "
            f'{{ type filter hook {chain_name} priority 0\\; }}'
        )

        print(f"✅ 建立 nftables table '{table_name}' 與 chain '{chain_name}' on {host.name}")

        host.cmd(f"setsid python3 /home/user/mininet/custom/modify_server_port.py > /dev/null 2>&1 &")

def clear_nftable(net):

    for host in net.hosts:
        host.cmd(f"nft delete table ip6 myfilter")

def clear_bpf(net):
    for host in net.hosts:
        host.cmd(f"sudo tc qdisc del dev {host.defaultIntf()} clsact")

def del_log_file():
    log_dir = "./pcap"

# 建立 log 目錄（如果還沒存在）
    os.makedirs(log_dir, exist_ok=True)

    # 清空 log 目錄中的所有檔案
    for filename in os.listdir(log_dir):
        file_path = os.path.join(log_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)  # 刪除檔案或連結
            elif os.path.isdir(file_path):
                import shutil
                shutil.rmtree(file_path)  # 若是子資料夾則整個刪除
        except Exception as e:
            print(f"❌ 無法刪除 {file_path}: {e}")


def run_mininet(topology_name):
    """ 啟動 Mininet 並讀取指定的拓撲 """
    del_log_file()
    setLogLevel('info')

    # **修正 JSON 路徑**
    json_path = os.path.expanduser("/home/user/mininet/custom/topology.json")

    # 讀取 JSON 檔案
    with open(json_path, 'r') as f:
        topology_config = json.load(f)
    
    if topology_name not in topology_config["topologies"]:
        print(f"❌ 找不到拓撲 `{topology_name}`，請檢查 JSON 檔案")
        return

    topology_data = topology_config["topologies"][topology_name]
    print(f"✅ 正在載入拓撲: {topology_data['name']}")

    topo = TopologyMaker(topology_data)
    net = Mininet(topo=topo, controller=RemoteController, switch=OVSSwitch, link=TCLink)
    ssh = sshd()
    root = ssh.buildRootNode(net, switch=net['s1'], ip='2001:db8::100/64')
    net.start()
    ssh.addRuleRootNode(root, routes = ['2001:db8::/64'])

    # 設定 IPv6 地址
    for host in net.hosts:
        if host.name in topo.host_ipv6:
            ipv6 = topo.host_ipv6[host.name]
            host.cmd(f'ip -6 addr add {ipv6}/64 dev {host.defaultIntf()}')
            print(f"Set IPv6 {ipv6} on {host.name}")
    
    ssh.startSSHService(net, root_pw='root')

    # 啟動 NetFilterQueue 來更新封包的 flow label
    start_netfilterqueue(net)
    # start_bpf(net)
    # create_nftable(net)

    # 顯示主機 MAC & IPv6
    for host in net.hosts:
        print(f"{host.name}: {host.MAC()} - {host.cmd('ip -6 addr show dev ' + str(host.defaultIntf()))}")

    CLI(net)  # 進入 Mininet CLI

    clear_netfilterqueue(net)
    # clear_nftable(net)
    # clear_bpf(net)

    net.stop()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run Mininet with Custom IPv6 Topologies")
    parser.add_argument(
        "topology",
        nargs="?",
        type=str,
        default="mesh_v2_topology", 
        help="Specify the topology name (e.g., mesh_topology, star_topology, ring_topology)")
    args = parser.parse_args()

    run_mininet(args.topology)

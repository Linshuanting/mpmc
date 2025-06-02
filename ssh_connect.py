import logging
import json
from dataclasses import dataclass
from ipaddress import IPv6Address, IPv6Network
from pathlib import Path
from typing import Dict, Optional, Sequence

import paramiko
from flask import Flask, request, jsonify

# 設定 logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

app = Flask(__name__)


@dataclass
class ConnectionInfo:
    hostname: str
    ip: str
    username: str
    password: Optional[str] = None
    key_file: Optional[str] = None


class SSHConnection:
    """Context manager for Paramiko SSHClient."""
    def __init__(self, info: ConnectionInfo):
        self.info = info
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def __enter__(self) -> paramiko.SSHClient:
        if self.info.key_file:
            self.client.connect(
                hostname=self.info.ip,
                username=self.info.username,
                key_filename=self.info.key_file
            )
        else:
            self.client.connect(
                hostname=self.info.ip,
                username=self.info.username,
                password=self.info.password
            )
        return self.client

    def __exit__(self, exc_type, exc_value, traceback):
        self.client.close()


class SSHManager:
    def __init__(self, file_folder: str = "/home/user/mpmc_implementation/mininet"):
        self._conns: Dict[str, ConnectionInfo] = {}
        self._default_nic: Dict[str, str] = {}
        self.file_folder = Path(file_folder)
        self.root_folder = Path("/home/user/mpmc_implementation")

    def add_host(
        self,
        hostname: str,
        ip: str,
        username: str,
        password: Optional[str] = None,
        key_file: Optional[str] = None
    ) -> None:
        self._conns[hostname] = ConnectionInfo(hostname, ip, username, password, key_file)
        logging.info(f"已儲存 {hostname} 的 SSH 連線資訊 ({ip})")

    def has_host(self, hostname: str) -> bool:
        return hostname in self._conns

    def execute_command(self, hostname: str, cmd: str) -> Optional[str]:
        info = self._conns.get(hostname)
        if not info:
            logging.error(f"無法執行 {hostname} 的指令，未提供 SSH 資訊")
            return None

        try:
            with SSHConnection(info) as client:
                stdin, stdout, stderr = client.exec_command(cmd)
                out = stdout.read().decode().strip()
                err = stderr.read().decode().strip()
            if err:
                logging.warning(f"[{hostname}] 命令錯誤: {err}")
                return err
            return out
        except Exception as e:
            logging.error(f"執行指令錯誤: {e}")
            return str(e)

    def _sftp_transfer(
        self,
        hostname: str,
        local_path: Path,
        remote_path: str,
        upload: bool = True
    ) -> None:
        info = self._conns.get(hostname)
        if not info:
            logging.error(f"無法 SFTP，未提供 {hostname} 的 SSH 資訊")
            return
        with SSHConnection(info) as client:
            sftp = client.open_sftp()
            try:
                if upload:
                    sftp.put(str(local_path), remote_path)
                    logging.info(f"{local_path} 已上傳至 {hostname}:{remote_path}")
                else:
                    sftp.get(remote_path, str(local_path))
                    logging.info(f"{hostname}:{remote_path} 已下載至 {local_path}")
            finally:
                sftp.close()

    def upload_file(self, hostname: str, local_path: str, remote_path: str) -> None:
        self._sftp_transfer(hostname, Path(local_path), remote_path, upload=True)

    def download_file(self, hostname: str, remote_path: str, local_path: str) -> None:
        self._sftp_transfer(hostname, Path(local_path), remote_path, upload=False)

    def get_default_nic(self, hostname: str) -> Optional[str]:
        if hostname in self._default_nic:
            return self._default_nic[hostname]

        logging.info(f"取得 {hostname} 的預設網卡")
        output = self.execute_command(hostname, "ip -br a")
        if not output:
            return None

        for line in output.splitlines():
            parts = line.split()
            if len(parts) > 1 and "UP" in parts[1]:
                nic = parts[0].split('@')[0]
                self._default_nic[hostname] = nic
                logging.info(f"✅ {hostname} Default NIC: {nic}")
                return nic

        logging.warning(f"⚠ {hostname} 無法獲取 Default NIC")
        return None

    def _ipv6_route_cmd(self, ip: str, nic: str, action: str) -> str:
        try:
            addr = IPv6Address(ip)
            net = IPv6Network(f"{addr}/16", strict=False).network_address
            return f"ip -6 route {action} {net}/16 dev {nic}"
        except ValueError:
            logging.error(f"無效 IPv6 地址: {ip}")
            return ""

    def add_ipv6_route(self, ip: str, nic: str) -> str:
        return self._ipv6_route_cmd(ip, nic, "add")

    def del_ipv6_route(self, ip: str, nic: str) -> str:
        return self._ipv6_route_cmd(ip, nic, "del")

    def _simple_cmd(self, template: str, ip: str, nic: str) -> str:
        return template.format(ip=ip, nic=nic)

    def add_ipv6_addr(self, ip: str, nic: str) -> str:
        return self._simple_cmd("ip addr add {ip} dev {nic} autojoin", ip, nic)

    def del_ipv6_addr(self, ip: str, nic: str) -> str:
        return self._simple_cmd("ip addr del {ip} dev {nic}", ip, nic)

    def add_ipv6_maddr(self, ip: str, nic: str) -> str:
        return self._simple_cmd("ip -6 maddr add {ip} dev {nic}", ip, nic)

    def del_ipv6_maddr(self, ip: str, nic: str) -> str:
        return self._simple_cmd("ip -6 maddr del {ip} dev {nic}", ip, nic)

    def _script_cmd(
        self,
        script: str,
        args: Sequence[str],
        background: bool = False,
        cwd: Optional[Path] = None
    ) -> str:
        path = (self.file_folder / script).as_posix()
        base = f"python {path} " + " ".join(args)
        if background:
            cwd_cmd = f"cd {cwd or self.file_folder} && " if cwd else ""
            return f"{cwd_cmd}setsid {base} > /dev/null 2>&1 &"
        return base

    def send_flabel(
        self,
        script: str = "flow_flabel.py",
        src_ip: str = "",
        dst_ip: str = "",
        start: int = 0x11000
    ) -> str:
        args = [f"--src_ip {src_ip}", f"--dst_ip {dst_ip}", f"--fl_number_start {start}"]
        return self._script_cmd(script, args)

    def send_flabel_bg(
        self,
        script: str = "flow_flabel_background.py",
        src_ip: str = "",
        dst_ip: str = "",
        start: int = 0x11000
    ) -> str:
        args = [f"--src_ip {src_ip}", f"--dst_ip {dst_ip}", f"--fl_number_start {start}", "--daemon"]
        return self._script_cmd(script, args, background=True)

    def iperf_server_multicast(
        self,
        host: str,
        mgrp: str = "ff38::1",
        port: int = 6001,
        duration: int = 10,
        log_dir: str = "simulation_result/raw_data"
    ) -> str:
        log_path = self.root_folder / log_dir / f"iperf_{mgrp.replace(':', '_')}_{host}_{port}.log"
        cmd = f"iperf -s -u -e -V -B {mgrp} -p {port} -i 1"
        return f"setsid timeout {duration} {cmd} > {log_path} 2>&1 &"

    def iperf_client(
        self,
        dst: str,
        bw: int = 10,
        duration: int = 10,
        port: int = 5001
    ) -> str:
        return f"setsid iperf -c {dst} -u -V -b {bw}M -t {duration} -p {port} > /dev/null 2>&1 &"

    def tcpdump_to_pcap(
        self,
        host: str,
        ipv6: str,
        nic: str,
        port: int,
        duration: int = 10
    ) -> str:
        pcap = self.file_folder / "pcap" / f"{ipv6}_{host}.pcap"
        return (
            f"setsid timeout {duration} "
            f"tcpdump -i {nic} udp port {port} -w {pcap} > /dev/null 2>&1 &"
        )

    def analyze_pcap(
        self,
        host: str,
        ipv6: str,
        wait: int = 10,
        script: str = "analysis_iperf_per_second.py"
    ) -> str:
        pcap = self.file_folder / "pcap" / f"{ipv6}_{host}.pcap"
        out_csv = f"{ipv6}_{host}.csv"
        args = [f"--pcap {pcap}", f"--wait {wait}", f"--output {out_csv}", "--ssh"]
        return self._script_cmd(script, args, background=True, cwd=self.file_folder / "custom")


ssh_manager = SSHManager()


@app.route("/add_host", methods=["POST"])
def api_add_host():
    data = request.json
    ssh_manager.add_host(
        hostname=data["hostname"],
        ip=data["ip"],
        username=data["username"],
        password=data.get("password"),
        key_file=data.get("key_file")
    )
    return jsonify({"message": f"{data['hostname']} 已新增"})


@app.route("/check_host", methods=["POST"])
def api_check_host():
    data = request.json
    result = ssh_manager.has_host(data["hostname"])
    return jsonify({"output": result})


@app.route("/execute_command", methods=["POST"])
def api_execute_command():
    data = request.json
    result = ssh_manager.execute_command(data["hostname"], data["command"])
    return jsonify({"output": result})


@app.route("/get_host_nic", methods=["POST"])
def api_get_host_nic():
    data = request.json
    nic = ssh_manager.get_default_nic(data["hostname"])
    return jsonify({"output": nic})


@app.route("/execute_set_ipv6_command", methods=["POST"])
def api_execute_set_ipv6_command():
    data = request.json
    nic = ssh_manager.get_default_nic(data["hostname"])
    if not nic:
        return jsonify({"error": "無法取得 NIC"}), 400
    cmd = ssh_manager.add_ipv6_addr(data["ip"], nic)
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_set_route_command", methods=["POST"])
def api_execute_set_route_command():
    data = request.json
    nic = ssh_manager.get_default_nic(data["hostname"])
    if not nic:
        return jsonify({"error": "無法取得 NIC"}), 400
    cmd = ssh_manager.add_ipv6_route(data["ip"], nic)
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_del_ipv6_command", methods=["POST"])
def api_execute_del_ipv6_command():
    data = request.json
    nic = ssh_manager.get_default_nic(data["hostname"])
    if not nic:
        return jsonify({"error": "無法取得 NIC"}), 400
    cmd = ssh_manager.del_ipv6_addr(data["ip"], nic)
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_del_route_command", methods=["POST"])
def api_execute_del_route_command():
    data = request.json
    nic = ssh_manager.get_default_nic(data["hostname"])
    if not nic:
        return jsonify({"error": "無法取得 NIC"}), 400
    cmd = ssh_manager.del_ipv6_route(data["ip"], nic)
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_send_packet_command", methods=["POST"])
def api_execute_send_packet_command():
    data = request.json
    cmd = ssh_manager.send_flabel_bg(
        src_ip=data["src"],
        dst_ip=data["dst"],
        start=data["flabel"]
    )
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_update_table_of_one_iperf_command", methods=["POST"])
def api_execute_update_modify_flabel_table_of_one_iperf_command():
    data = request.json
    cmd = ssh_manager._script_cmd(
        script="update_table_one_iperf.py",
        args=[
            f"--ip {data['dst']}",
            f"--dport {data['dport']}",
            f"--weights {','.join(map(str, data['weights']))}"
        ]
    )
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_update_table_command", methods=["POST"])
def api_execute_update_modify_flabel_table_command():
    data = request.json
    cmd = ssh_manager._script_cmd(
        script="update_table.py",
        args=[f"--ip {data['dst']}", f"--dport {data['dport']}"]
    )
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_iperf_server_command", methods=["POST"])
def api_execute_iperf_server_command():
    data = request.json
    last_result = None
    for host in data["hostname"]:
        cmd = ssh_manager.iperf_server_multicast(
            host=host,
            mgrp=data["dst"],
            port=data["port"],
            duration=data.get("time", 10)
        )
        last_result = ssh_manager.execute_command(host, cmd)
    return jsonify({"output": last_result})


@app.route("/execute_iperf_client_command", methods=["POST"])
def api_execute_iperf_client_command():
    data = request.json
    cmd = ssh_manager.iperf_client(
        dst=data["dst"],
        bw=data["bw"],
        duration=data["time"],
        port=data["port"]
    )
    result = ssh_manager.execute_command(data["hostname"], cmd)
    return jsonify({"output": result})


@app.route("/execute_nftable_add_rule_command", methods=["POST"])
def api_execute_nftable_add_rule_command():
    data = request.json

    hostname = data["hostname"]
    table = data.get("table", "myfilter")
    chain = data.get("chain", "prerouting")
    queue_num = data.get("queue", 2)

    # 支援單個 port 或多個 port
    ports = data.get("ports")
    port = data.get("port")

    if ports:
        port_expr = ", ".join(str(p) for p in ports)
        port_match = f"udp dport {{ {port_expr} }}"
    elif port:
        port_match = f"udp dport {port}"
    else:
        return jsonify({"error": "Missing 'port' or 'ports' in request"}), 400

    add_cmd = f"nft add rule ip6 {table} {chain} {port_match} queue num {queue_num}"
    result = ssh_manager.execute_command(hostname, add_cmd)
    return jsonify({"command": add_cmd, "output": result})


@app.route("/execute_send_mapping_to_socket", methods=["POST"])
def api_send_mapping_to_socket():
    data = request.json

    hostname = data["hostname"]
    ip = data["ip"]
    fl_p_dict = data["fl_p_dict"]
    script_path = "/home/user/mininet/custom/update_table_server_port.py"

    if not isinstance(fl_p_dict, dict):
        return jsonify({"error": "'fl_p_dict' must be a dict"}), 400

    json_mapping_str = json.dumps(fl_p_dict)
    cmd = f"python3 {script_path} --ip {ip} --mapping '{json_mapping_str}'"
    result = ssh_manager.execute_command(hostname, cmd)

    return jsonify({"hostname": hostname, "command": cmd, "output": result})


@app.route("/execute_tcpdump_and_get_csv_command", methods=["POST"])
def api_execute_tcpdump_and_get_csv_command():
    data = request.json
    duration = data["time"] + 5
    hosts = data["hostname"]
    results = []

    for host in hosts:
        host_results = []

        start_cmd = ssh_manager.tcpdump_to_pcap(
            host=host,
            ipv6=data["dst_ip"],
            nic=ssh_manager.get_default_nic(host),
            port=data["dport"],
            duration=duration
        )
        host_results.append(ssh_manager.execute_command(host, start_cmd))

        analyze_cmd = ssh_manager.analyze_pcap(
            host=host,
            ipv6=data["dst_ip"],
            wait=duration
        )
        host_results.append(ssh_manager.execute_command(host, analyze_cmd))

        results.append(host_results)

    return jsonify({"output": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4888)

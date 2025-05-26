import sys

from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import lg, info
from mininet.node import Node, OVSSwitch, Controller, RemoteController
from mininet.topolib import TreeTopo
from mininet.util import waitListening
from mininet.topo import Topo
import ipaddress

class sshd():

    def set_IPv6(self, node, ip, intf):
        # 下面這兩個都要加入，才能正確的加入 ipv6 addr
        node.setIP(ip, intf=intf)
        node.cmd(f'ip -6 addr add {ip} dev {intf}')
        info(f'Add {ip} via {intf}\n')

    def buildRootNode(self, net, switch, ip):
        root = Node( 'root', inNamespace=False)
        link = net.addLink(switch, root)
        self.set_IPv6(root, ip, link.intf2)
        root.cmd(f'ip link set {link.intf2} address 00:00:00:00:ff:ff')  # 手動設置 MAC

        return root
    
    def addRuleRootNode(self, root, routes):
        for route in routes:
            root.cmd(f'ip -6 route add {route} dev {root.defaultIntf()}')
            info(f"Added route {route} via {root.defaultIntf()}\n")
    
    def startSSHService(self, net, cmd='/usr/sbin/sshd', opts='-D', root_pw='password'):

        for host in net.hosts:
            
            host.cmd("grep -q '^PermitRootLogin yes' /etc/ssh/sshd_config || echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config")
            host.cmd("grep -q '^PasswordAuthentication yes' /etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config")
            host.cmd("grep -q '^PermitEmptyPasswords no' /etc/ssh/sshd_config || echo 'PermitEmptyPasswords no' >> /etc/ssh/sshd_config")
            host.cmd("grep -q '^UsePAM yes' /etc/ssh/sshd_config || echo 'UsePAM yes' >> /etc/ssh/sshd_config")
            host.cmd("sed -i 's/^PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config")

            host.cmd("mkdir -p /run/sshd && chmod 755 /run/sshd")

            host.cmd(f"echo 'root:{root_pw}' | chpasswd")

            host.cmd( cmd + ' ' + opts + '&' )
    
        for server in net.hosts:
            info(server.cmd(f'netstat -tuln | grep 22'))
            # waitListening( server=server, port=22, timeout=1 )

        info( "\n*** Hosts are running sshd at the following addresses:\n" )
        for host in net.hosts:
            info( host.name, host.IP(), '\n' )
    
    def sshd(self, network, cmd='/usr/sbin/sshd', opts='-D',
          ip='2001:db8::100/128', routes=None, switch=None ):
        if not switch:
            switch = network[ 's1' ]  # switch to use
        if not routes:
            routes = [ '2001:db8::/64' ]

        root = self.buildRootNode(network, switch, ip)

        network.start()

        self.addRuleRootNode(root, routes)
        self.startSSHService(network, cmd=cmd, opts=opts)

        CLI( network )

        network.stop()

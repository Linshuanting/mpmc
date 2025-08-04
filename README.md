# MPMC Project

This Project is for the thesis of **Implementation of Multipath-Enabled Multicast for the Multi-Commodity
Flow Problem with SDN in AI Topology**, which used multipath and multicast technique in Software-Defined Network (SDN), then solved the one-to-many MCF problem.

**在 AI 拓撲中基於軟體定義網路之多重貨物流問題的多路徑群播實作**

## Environment Setup

This repository provides a one-command installation script to set up a complete Software-Defined Networking (SDN) development environment. The environment includes:

- Python 3.9.13 managed by [pyenv](https://github.com/pyenv/pyenv)
- [Ryu SDN controller](https://github.com/faucetsdn/ryu)
- [Mininet](http://mininet.org/)

---

## 📁 Directory Structure

```
mpmc_implementation/
├── install.sh # All-in-one installation script
├── ryu_controller/ # Your custom Ryu applications
├── mininet/ # Your custom mininet applications
├── ssh_connect.py # Your ssh server applications
├── external/
│ ├── ryu/ # Cloned Ryu controller source
│ └── mininet/ # Cloned Mininet emulator
├── simulation_result/ # Logs and experiment output
├── .python-version # pyenv local version
└── requirements.txt # Python package list
```

---

## ✅ Requirements

- Ubuntu 22.04 or later
- Internet connection to clone GitHub repositories
- `sudo` privileges

---

## 🚀 Quick Start

1. Clone this repository:

```bash
git clone https://github.com/Linshuanting/mpmc
cd mpmc
```
2. Installation of Mininet & Ryu:
```bash
./install.sh
```
3. Restart command line

4. Checking Installation of Mininet & RyuS
```bash
ryu-manager --version
sudo mn --version
```

5. Set the config according to your environment
```bash
cd common
# Update config.py to match your environment
```

## 🚀 Usage
1. Start the Ryu Controller
```bash
ryu-manager ryu_controller/MyController.py
```
2. Launch Custom Topology
```bash
sudo python mininet/topo_maker.py <topology_name>
# the topoglogy data saved in mininet/topology.json
# sudo python mininet/topo_maker.py spine_leaf_topology
```
3. Launch ssh server
```bash
python ssh_connect.py
```
4. Start Applclication GUI
```bash
python ryu_controller/PyQt_GUI/gui.py
```
5. Generating Result
```text
Press the button in GUI
```
6. Check Raw Data Result
```text
Results are saved in the simulation_result/raw_data folder.
```

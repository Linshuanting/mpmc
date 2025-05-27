from PyQt5.QtCore import QThread, pyqtSignal
import requests
import json
from ryu_controller.tools.utils import tuple_key_to_str
from ryu_controller.tools.commodity_parser import commodity_parser as cm_parser
from ryu_controller.PyQt_GUI.gui_tools import get_bandwidth, get_commodity, run_algorithm

class RestAPIClient:
    def __init__(self, url):
        self.url = url
        self.ssh_url = None
        self.latest_links = None
        self.latest_nodes = None
        self.latest_links_bw = None
        self.algorithm_result = []
        self.record_result = []
        self.commodity_counter = 1
        
        self.worker = None
        self.upload_worker = None
        self.fetch_worker = None
        self.set_host_switch_worker = None
        self.send_packet_worker = None
        self.multi_group_worker = None
        self.send_pkt_worker = None

    def run_algorithm_process(self, result_text):
        if self.latest_links is None or self.latest_nodes is None:
            result_text.setPlainText("❌ 错误: 还未获取到数据，等待自动 fetch 完成")
            return

        result_text.setPlainText("🚀 Running algorithm...")
        self.worker = AlgorithmWorker(self.latest_nodes, self.latest_links_bw, self.commodity_counter)
        self.worker.finished.connect(lambda commodities, res: self.on_algorithm_finished(commodities, res, result_text))
        self.worker.error.connect(lambda err: result_text.setPlainText(f"⚠ 运行失败: {err}"))
        self.worker.start()

    def on_algorithm_finished(self, commodities, result, result_text):
        try:
            parser = cm_parser()
            packet = []
            for com in commodities:
                commodity = parser.serialize_commodity(
                    name=com["name"],
                    src=com["source"],
                    dsts=com["destinations"],
                    demand=com["demand"],
                    paths=result.get(com["name"], [])
                )
                packet = parser.add_packet(commodity, packet)
            
            self.algorithm_result = packet

            output_text = json.dumps(packet, indent=4, ensure_ascii=False)
            # self.upload_commodity_data(output_text, result_text)
            result_text.setPlainText(f"✅ 計算完成，可準備上傳到資料庫\n {output_text}")
        except Exception as e:
            result_text.setPlainText(f"⚠ 结果处理失败: {str(e)}")

    def upload_commodity_data(self, result_text, record_text):
        data = self.algorithm_result
        result_text.setPlainText(f"📡 Uploading data to server...\n{data}")
        self.upload_worker = UploadWorker(self.url, data)
        self.upload_worker.finished.connect(lambda res: self.on_upload_finished(res, result_text, record_text, data))
        self.upload_worker.error.connect(lambda err: result_text.setPlainText(f"⚠ 上傳失敗: {err}"))
        self.upload_worker.start()

    def on_upload_finished(self, response, result_text, record_text, data):
        
        json_data = json.dumps(data, indent=4, ensure_ascii=False)
        result_text.setPlainText(f"✅ Upload finished:{response}\n{json_data}")
        
        self.commodity_counter+=len(data)
        self.record_algorithm_data(record_text)

    def record_algorithm_data(self, record_text):
        try:
            parser = cm_parser()

            packet = self.algorithm_result

            name_list, commodities = parser.parser(packet)

            records = [
                {
                    "name": name,
                    "source": parser.parse_src(name, commodities),
                    "destinations": parser.parse_dsts(name, commodities),
                    "total_demand": parser.parse_demand(name, commodities),
                }
                for name in name_list
            ]
            
            self.record_result.extend(records)

            output_text = json.dumps(self.record_result, indent=4, ensure_ascii=False)

            record_text.setPlainText(f"✅ 新增規則\n {output_text}")
        except Exception as e:
            record_text.setPlainText(f"⚠ 结果处理失败: {str(e)}")

    def set_host_and_switch(self, record_text):
        output_text = json.dumps(self.record_result, indent=4, ensure_ascii=False)
        record_text.setPlainText(f"✅ Start writting rule to hosts and switches\n {output_text}")
        
        packet = []
        parser = cm_parser()
        for info in self.record_result:
            commodity = parser.serialize_commodity(
                name=info["name"],
                src=info["source"],
                dsts=info["destinations"],
                demand=info["total_demand"]
            )
            packet = parser.add_packet(commodity, packet)
        
        self.set_host_switch_worker = SetHostAndSwitchWorker(self.url, packet)
        self.set_host_switch_worker.finished.connect(lambda res:self.on_set_rule_finished(res, output_text, record_text))
        self.set_host_switch_worker.error.connect(lambda err: record_text.setPlainText(f"⚠ 傳送失敗: {err}\n{output_text}"))
        self.set_host_switch_worker.start()

    def on_set_rule_finished(self, respone, data, record_text):
        record_text.setPlainText(f"✅ Setting Rule to hosts and switches finished:\n{data}")

    def send_packet(self, send_packet_text):
        
        packet = []
        parser = cm_parser()
        for info in self.record_result:
            commodity = parser.serialize_commodity(
                name=info["name"],
                src=info["source"],
                dsts=info["destinations"],
                demand=info["total_demand"]
            )
            packet = parser.add_packet(commodity, packet)
        
        output_text = json.dumps(self.record_result, indent=4, ensure_ascii=False)
        send_packet_text.setPlainText(f"📡 Start sending packet...\n{output_text}")
        
        self.send_packet_worker = SendPacketWorker(self.url, packet)
        self.send_packet_worker.finished.connect(lambda res:self.on_send_packet_finished(res, send_packet_text))
        self.send_packet_worker.error.connect(lambda err: send_packet_text.setPlainText(f"⚠ 傳送失敗: {err}"))
        self.send_packet_worker.start()

    def on_send_packet_finished(self, respone, send_packet_text):
        self.record_result.clear()
        send_packet_text.setPlainText(f"✅ sending packet finished:\n{respone }")
    
    def test_send_packet(self, send_packet_text):
        commodities = [info["name"] for info in self.record_result]
        send_packet_text.setPlainText("📡 Get MultiGroup Data... \n")


        self.multi_group_worker = MultiGroupWorker(self.url, commodities)
        self.multi_group_worker.finished.connect(self.on_multigroup_finished)
        self.multi_group_worker.error.connect(lambda e: print(f"❌ MultiGroup error: {e}"))
        self.multi_group_worker.start()

    def on_multigroup_finished(self, multigroup_result):
        print("✅ MultiGroup done, result:", multigroup_result)

        self.send_pkt_workers = []  # 🔹 用 list 存下所有 worker 實例

        for commodity in multigroup_result:
            worker = SendPktWorker(self.ssh_url)
            worker.set_data(
                src=commodity["src"],
                dsts=commodity["dsts"],
                dst_ip=commodity["dst_ip"],
                s_dport_list=commodity["s_dport"],
                dport=commodity["dport"],
                bw_list=commodity["bw"],
                time=5
            )
            worker.finished.connect(self.on_sendpkt_finished)
            worker.error.connect(lambda e: print(f"❌ SendPkt error: {e}"))
            worker.start()

            self.send_pkt_workers.append(worker)  # ✅ 保留參考避免被 GC 清掉
    
    def on_sendpkt_finished(self, result):
        print("📦 SendPktWorker finished with result:")
        print(result)

        # 將這次結果存入列表
        if not hasattr(self, 'sendpkt_results'):
            self.sendpkt_results = []

        self.sendpkt_results.append(result)

        # 自訂完成條件：當所有 worker 都完成
        if len(self.sendpkt_results) == len(self.send_pkt_workers):
            print("✅ 所有封包傳送任務完成！")
            # 可以統一處理所有結果
            for idx, res in enumerate(self.sendpkt_results):
                print(f"🔹 Worker {idx} result:")
                print(res)

            # ✨ 顯示到 GUI 或 log 等處理都可加在這裡
            
            # 清空 worker 與結果記憶體
            self.send_pkt_workers.clear()
            self.sendpkt_results.clear()


    def fetch_topology_data(self, links_text, hosts_text):
        self.fetch_worker = FetchWorker(self.url)
        self.fetch_worker.finished.connect(lambda data: self.on_fetch_finished(data, links_text, hosts_text))
        self.fetch_worker.error.connect(lambda err: links_text.setPlainText(f"数据获取失败: {err}"))
        self.fetch_worker.start()

    def on_fetch_finished(self, data, links_text, hosts_text):
        try:
            
            links_data = data.get("links", {})
            links_bw = data.get("links_bw", {})

            formatted_links = []
            parsed_links = []

            nodes_set = set()  # 存储 nodes，避免重复

            for key, value in links_data.items():
                # 分割 key 和 value
                src_device, dst_device = key.rsplit("-", 1)  # 源设备
                src_port, dst_port = value.rsplit("-", 1)  # 目标设备
                bw = links_bw.get(key, 0)
                # links_bw[key] = float(bw)

                nodes_set.add(src_device)
                nodes_set.add(dst_device)

                # 设备类型检查
                src_is_host = src_device.startswith("h")
                dst_is_host = dst_device.startswith("h")

                src_type = "Host" if src_is_host else "Switch"
                dst_type = "Host" if dst_is_host else "Switch"

                src_formatted = f"{src_type} {src_device} (eth{src_port})"
                dst_formatted = f"{dst_type} {dst_device} (eth{dst_port})"

                # **排序规则**：Host (h) 设备在前，Switch (s) 设备在后
                def get_sort_key(device):
                    if device.startswith("h"):
                        # **对于 `hffff` 这样的非数字主机，保持原始名称**
                        try:
                            return (0, int(device[1:]))  # `h1`, `h2`, `h3` 正常转换
                        except ValueError:
                            return (0, float("inf"))  # `hffff` 作为字符串排序
                    else:
                        return (1, int(device))  # Switch `sX` 仍然使用数字排序

                src_sort_key = get_sort_key(src_device)
                dst_sort_key = get_sort_key(dst_device)

                # 存储解析后的数据和排序键
                parsed_links.append(((src_sort_key, dst_sort_key), f"{src_formatted} → {dst_formatted}, bw: {bw} Mbps"))

            # **按排序规则排序**
            parsed_links.sort(key=lambda x: (x[0][0], x[0][1]))

            # 提取排序后的数据
            formatted_links = [entry[1] for entry in parsed_links]

            # 解析 `hosts` 数据
            hosts = {key: value for key, value in data.get("hosts", {}).items()}
            hosts_data = json.dumps(data.get("hosts", {}), indent=4, ensure_ascii=False)

            self.latest_links = links_data
            self.latest_nodes = list(sorted(nodes_set))
            self.latest_links_bw = links_bw

            links_len = len(links_data) - len(hosts)*2
            print(f"switch links amount: {links_len}")

            # 更新 GUI 文本框
            links_text.setPlainText("\n".join(formatted_links))
            hosts_text.setPlainText(hosts_data)
        
        except Exception as e:
            links_text.setPlainText(f"数据解析失败: {e}")
            hosts_text.setPlainText(f"数据解析失败: {e}")
    
    def set_ssh_url(self, url):
        self.ssh_url = url

FETCH_DATA_LINK = "/topology"
GET_MULTIGROUP_LINK = "/multiGroupData"
UPLOAD_DATA_LINK = "/add_commodity_request"
UPDATE_HOST_SWITCH_DATA_LINK = "/update_host_and_switch_through_commodities"
SEND_PACKET_THROUGH_DATA_LINK = "/send_packet"

class AlgorithmWorker(QThread):
    finished = pyqtSignal(list, dict)
    error = pyqtSignal(str)

    def __init__(self, nodes, links_bw, counter=1):
        super().__init__()
        self.nodes = nodes
        self.links = {
            link: float(bw) if bw not in [None, "None"] else 0.0
            for link, bw in links_bw.items()
        }
        self.cnt = counter

    def run(self):
        try:
            print("🚀 Running algorithm in background thread...")
            # capacities = get_bandwidth(self.links)
            print(f"algorithm start links: {self.links}")
            input_commodities = get_commodity(self.nodes, 4, start=self.cnt)
            result = run_algorithm(self.nodes, self.links, input_commodities)
            print(f"Algorithm result:{result}")
            self.finished.emit(input_commodities, result)
        except Exception as e:
            self.error.emit(str(e))


class UploadWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url, data):
        super().__init__()
        self.url = url
        self.data = data

    def run(self):
        try:
            json_data = self.data if isinstance(self.data, str) else json.dumps(self.data, indent=4)
            headers = {'Content-Type': 'application/json'}
            url = f"{self.url}{UPLOAD_DATA_LINK}"
            print(f"📤 Uploading Data to {url}...")
            response = requests.post(url, data=json_data, headers=headers)
            response.raise_for_status()
            self.finished.emit(response.text)
        except requests.exceptions.RequestException as e:
            self.error.emit(f"❌ Error posting data to API: {e}")

class SetHostAndSwitchWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url, data):
        super().__init__()
        self.url = url
        self.data = data

    def run(self):
        try:
            json_data = self.data if isinstance(self.data, str) else json.dumps(self.data, indent=4)
            headers = {'Content-Type': 'application/json'}
            url = f"{self.url}{UPDATE_HOST_SWITCH_DATA_LINK}"
            print(f"📤 Setting Data to Host and Switch, {url}...")
            response = requests.post(url, data=json_data, headers=headers)
            response.raise_for_status()
            self.finished.emit(response.text)
        except requests.exceptions.RequestException as e:
            self.error.emit(f"❌ Error posting data to API: {e}")

class SendPacketWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url, data):
        super().__init__()
        self.url = url
        self.data = data
    
    def run(self):
        try:
            json_data = self.data if isinstance(self.data, str) else json.dumps(self.data, indent=4)
            headers = {'Content-Type': 'application/json'}
            url = f"{self.url}{SEND_PACKET_THROUGH_DATA_LINK}"
            print(f"📤 Setting Data to Host and Switch, {url}...")
            response = requests.post(url, data=json_data, headers=headers)
            response.raise_for_status()
            self.finished.emit(response.text)
        except requests.exceptions.RequestException as e:
            self.error.emit(f"❌ Error fetching data from API: {e}")

class FetchWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            url = f"{self.url}{FETCH_DATA_LINK}"
            response = requests.get(url)
            response.raise_for_status()
            self.finished.emit(response.json())
        except requests.exceptions.RequestException as e:
            self.error.emit(f"❌ Error fetching data from API: {e}")

class MultiGroupWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, url, commodities_list):
        super().__init__()
        self.url = url
        self.commodities_list = commodities_list
    
    def run(self):
        try:
            url = f"{self.url}{GET_MULTIGROUP_LINK}"
            response = requests.get(url, 
                                    params={'commodities': json.dumps(self.commodities_list)})
            response.raise_for_status()
            self.finished.emit(response.json())
        except requests.exceptions.RequestException as e:
            self.error.emit(f"❌ Error fetching data from API: {e}") 

class SendPktWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    iperf_client_link = "/execute_iperf_client_command"
    iperf_server_link = "/execute_iperf_server_command"
    update_table_of_NFQUEUE_link = "/execute_update_table_command"

    def __init__(self, url):
        super().__init__()
        self.url = url
    
    def set_data(self, src, dsts, dst_ip, s_dport_list, dport, bw_list, time=5):
        self.src = src
        self.dsts = dsts
        self.dst_ip = dst_ip
        self.s_dport_list = s_dport_list  # 改名為 list
        self.dport = dport
        self.bw_list = bw_list
        self.time = time

    def post_client_data(self, host, bw, s_dport):
        return {
            "hostname": host,
            "dst": self.dst_ip,
            "bw": bw,
            "time": self.time,
            "port": s_dport
        }
    
    def post_server_data(self, hosts):
        return {
            "hostname": hosts,
            "dst": self.dst_ip,
            "port": self.dport
        }

    def post_table_data(self, host):
        return {
            "hostname": host,
            "dst": self.dst_ip,
            "port": self.dport
        }
    
    def execute_cmd(self, link, json_data):
        
        try:
            exe_url = f"{self.url}{link}"
            headers = {'Content-Type': 'application/json'}
            print(f"📤 Setting Data to Host and Switch, {exe_url}...")
            response = requests.post(exe_url, data=json_data, headers=headers)
            return response
        except requests.exceptions.RequestException as e:
            return (f"❌ Error send packet data from API: {e}")


    def run(self):
        all_update_res = []
        all_server_res = []
        all_client_res = []

        for s_dport, bw in zip(self.s_dport_list, self.bw_list):
            # 每次替換 port 值

            update_table_data = self.post_table_data(self.src)
            update_res = self.execute_cmd(self.update_table_of_NFQUEUE_link, update_table_data)

            iperf_server_data = self.post_server_data(self.dsts)
            server_res = self.execute_cmd(self.iperf_server_link, iperf_server_data)

            iperf_client_data = self.post_client_data(self.src, bw, s_dport)  # 這裡是 client 的 port
            client_res = self.execute_cmd(self.iperf_client_link, iperf_client_data)

            # 收集結果
            all_update_res.append(update_res)
            all_server_res.append(server_res)
            all_client_res.append(client_res)

        self.finished.emit({
            "update_res": all_update_res,
            "server_res": all_server_res,
            "client_res": all_client_res
        })

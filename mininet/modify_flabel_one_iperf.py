# ✅ 改進後版本：支援指定目標 DPort 並根據 weight 使用 flabel 分 tree 路徑

import socket
import threading
import json
import struct
from netfilterqueue import NetfilterQueue
from scapy.all import IPv6, UDP
from scapy.utils import checksum
from ipaddress import IPv6Address
import multiprocessing
import random
import ctypes
import ctypes.util
from bisect import bisect
import atexit

import logging

# 初始化 log 設定
logging.basicConfig(
    filename="/home/user/mpmc_implementation/mininet/log/nfqueue_log.txt",
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

atexit.register(logging.shutdown)

# 定義 flow label 的不同範圍（視 tree 數量使用）
flow_label_tree_ranges = {
    0: (0x81000, 0x81FFF),
    1: (0x82000, 0x82FFF),
    2: (0x83000, 0x83FFF),
    3: (0x84000, 0x84FFF),
    4: (0x85000, 0x85FFF),
    5: (0x86000, 0x86FFF),
    6: (0x87000, 0x87FFF),
    7: (0x88000, 0x88FFF),
    8: (0x89000, 0x89FFF),
    9: (0x8a000, 0x8aFFF),
    10: (0x8b000, 0x8bFFF),
    11: (0x8c000, 0x8cFFF),
    12: (0x8d000, 0x8dFFF),
    13: (0x8e000, 0x8eFFF),
    14: (0x8f000, 0x8fFFF),
}

manager = multiprocessing.Manager()
shared_labels = {idx: manager.Value('i', base) for idx, (base, _) in flow_label_tree_ranges.items()}
ip_tree_config = manager.dict()  # {'ff38::1': {'dport': 6001, 'weights': [2, 3, 5]}}

def weighted_choice(weights):
    total = sum(weights)
    r = random.uniform(0, total)
    upto = 0
    for i, w in enumerate(weights):
        if upto + w >= r:
            return i
        upto += w

flow_label_pool = {
    idx: {"base": base, "max": max_, "current": base, "lock": threading.Lock()}
    for idx, (base, max_) in flow_label_tree_ranges.items()
}

def build_weight_cdf(weights):
    total = sum(weights)
    cdf = []
    acc = 0
    for w in weights:
        acc += w
        cdf.append(acc / total)
    return cdf

def fast_weighted_choice(cdf):
    r = random.random()
    return bisect(cdf, r)

def checksum(data):
    if len(data) % 2:
        data += b'\x00'
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF

def new_modify_packet(packet):
    raw = bytearray(packet.get_payload())
    ip6_offset = 0
    udp_offset = ip6_offset + 40

    logging.info(f"[DEBUG] First 128 bytes: {raw[:128].hex(' ')}")

    dst_ip = bytes(raw[ip6_offset+24 : ip6_offset+40])
    config = ip_tree_config.get(dst_ip)
    logging.info(f"[DST IP] IP: {IPv6Address(dst_ip)}")

    if config is None:
        logging.info(f"[NOPASS] Unmatched IP: {IPv6Address(dst_ip)} → accept()")
        packet.accept()
        return

    weights = config["weights"]
    cdf = config["cdf"]
    output_dport = config["dport"]

    tree_idx = fast_weighted_choice(cdf)
    pool = flow_label_pool.get(tree_idx)

    if pool is None:
        logging.info(f"[PASS] Invalid Tree Index {tree_idx} for {IPv6Address(dst_ip)} → accept()")
        packet.accept()
        return

    with pool["lock"]:
        curr = pool["current"]
        base = pool["base"]
        new_label = base + ((curr - base + 1) % 0x1000)
        pool["current"] = new_label


    # checksum_raw = raw[udp_offset + 6 : udp_offset + 8]
    # checksum_value = struct.unpack("!H", checksum_raw)[0]
    # logging.info(f"[Origin Checksum] 0x{checksum_value:04x}")

    # udp_checksum = calculate_udp_checksum(raw, ip6_offset, udp_offset)
    # logging.info(f"[Check Checksum Formula] 0x{udp_checksum:04x}")

    # Flow label
    raw[ip6_offset+1] = (raw[ip6_offset+1] & 0xF0) | ((new_label >> 16) & 0x0F)
    raw[ip6_offset+2] = (new_label >> 8) & 0xFF
    raw[ip6_offset+3] = new_label & 0xFF

    # DPort
    raw[udp_offset+2] = (output_dport >> 8) & 0xFF
    raw[udp_offset+3] = output_dport & 0xFF

    udp_checksum = calculate_udp_checksum(raw, ip6_offset, udp_offset)
    # logging.info(f"[New Calculate Checksum] 0x{udp_checksum:04x}")

    raw[udp_offset+6] = (udp_checksum >> 8) & 0xFF
    raw[udp_offset+7] = udp_checksum & 0xFF

    packet.set_payload(bytes(raw))
    # logging.info(f"[MODIFY] {IPv6Address(dst_ip)} → Tree {tree_idx}, DPort: {output_dport}, Label: {hex(new_label)}")
    packet.accept()

def calculate_udp_checksum(raw, ip6_offset, udp_offset):
    import struct
    # 提取 IPv6 來源/目的位址
    src_ip = raw[ip6_offset+8:ip6_offset+24]
    dst_ip = raw[ip6_offset+24:ip6_offset+40]
    # 取得 UDP 長度（需確認是否已正確設置）
    udp_len = struct.unpack("!H", raw[udp_offset+4:udp_offset+6])[0]
    # 構造 Pseudo Header
    pseudo_header = (
        src_ip +
        dst_ip +
        struct.pack("!I3xB", udp_len, 17)  # 4-byte length + 3 reserved + 1-byte next header
    )

    udp_payload = raw[udp_offset : udp_offset + udp_len]

    # set checksum = 0
    udp_payload[6] = 0
    udp_payload[7] = 0
    udp_checksum = checksum(pseudo_header + udp_payload)

    return udp_checksum

def start_nfqueue():
    nfqueue = NetfilterQueue()
    # nfqueue.bind(1, modify_packet)
    nfqueue.bind(1, new_modify_packet)

    print("🚦 NFQUEUE listening...")
    try:
        nfqueue.run()
    except KeyboardInterrupt:
        nfqueue.unbind()


def socket_server(host="0.0.0.0", port=9999):
    print(f"📡 Socket server started on {host}:{port}")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, port))
    s.listen()

    while True:
        conn, addr = s.accept()
        data = conn.recv(1024).decode()
        try:
            req = json.loads(data)
            ip = IPv6Address(req.get("ip")).packed
            weights = req.get("weights")  # e.g. [2, 1, 3]
            dport = int(req.get("dport"))

            if ip and weights and dport:
                ip_tree_config[ip] = {"weights": weights, "dport": dport, "cdf": build_weight_cdf(weights)}
                logging.info(f"Add ip:{IPv6Address(ip)} to config table -> dport:{dport}, weight:{weights}")
                conn.send(f"✅ Config updated for {ip} → DPort {dport}, Weights: {weights}\n".encode())
                print(f"✅ Updated: {ip} → DPort {dport}, Weights: {weights}")
            else:
                conn.send("❌ Missing required fields.\n".encode())
        except Exception as e:
            conn.send(f"❌ Error: {str(e)}\n".encode())
        conn.close()


if __name__ == "__main__":
    nfqueue_process = multiprocessing.Process(target=start_nfqueue)
    nfqueue_process.start()

    t_socket = threading.Thread(target=socket_server, daemon=True)
    t_socket.start()

    nfqueue_process.join()
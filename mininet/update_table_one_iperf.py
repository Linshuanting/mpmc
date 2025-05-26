import socket
import json
import argparse

def update(ip, dport, weights, host="localhost", port=9999):
    payload = {
        "ip": ip,
        "dport": dport,
        "weights": weights
    }
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    s.send(json.dumps(payload).encode())
    print(s.recv(1024).decode())
    s.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update flow config for multicast IP")
    parser.add_argument("--ip", required=True, help="Multicast IP to map (e.g. ff38::1)")
    parser.add_argument("--dport", required=True, type=int, help="Real destination port to rewrite to")
    parser.add_argument("--weights", required=True, help="Comma-separated tree weights, e.g. 2,3,5")

    args = parser.parse_args()
    weights_list = [int(w) for w in args.weights.split(",")]
    update(args.ip, args.dport, weights_list)

import re, os
import shutil
import pandas as pd
import matplotlib.pyplot as plt

current_dir = os.path.dirname(os.path.abspath(__file__))
raw_data_dir = f"{current_dir}/raw_data"
tmp_dir = f"{current_dir}/tmp"


def create_incremental_result_dir(base_name="result"):
    # 取得當前 .py 檔案所在資料夾
    base_path = os.path.dirname(os.path.abspath(__file__))

    i = 1
    while True:
        folder_name = f"{base_name}{i}"
        full_path = os.path.join(base_path, folder_name)
        if not os.path.exists(full_path):
            os.makedirs(full_path)
            print(f"[✅] Created directory: {full_path}")
            return full_path
        i += 1

def raw_data_analysis(tmp_dir, file_name="iperf_multicast_per_second.csv"):
    records = []
    filename_pattern = re.compile(r"iperf_(ff38__\d+)_([a-z]+\d+)_\d+\.log")
    line_pattern_m = re.compile(
        r"\[\s*\d+\]\s+"                              # [  1]
        r"(\d+\.\d+)-(\d+\.\d+)\s+sec\s+"             # 0.0000-1.0000 sec
        r"([\d\.]+)\s+(K|M)Bytes\s+"                  # 1.63 MBytes
        r"([\d\.]+)\s+Mbits/sec\s+"                   # 13.7 Mbits/sec
        r"([\d\.]+)\s+ms\s+"                          # Jitter
        r"(\d+)/(\d+)\s+\(([\d\.]+)%\)\s+"            # 0/1178 (0.00%)
        r"([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+)\s+ms\s+"  # latency avg/min/max/stdev
        r"(\d+)\s+pps\s+(\d+)"                        # 1179 pps 6382
    )

    # 1: start time, 2: end time, 5: throughput/per sec, 6: jitter, 7: packet loss, 8: total packet
    # 9: loss ratio, 10: latency avg, 11: latency min, 12: latency max, 13: latency stddev
    # 14: pps, 15: NetPwr

    for filename in os.listdir(raw_data_dir):
        match = filename_pattern.match(filename)
        print(match)
        if not match:
            continue
        group_ip, host = match.groups()
        with open(os.path.join(raw_data_dir, filename), "r") as f:
            for line in f:
                m = line_pattern_m.search(line)
                if m:
                    start_time = float(m.group(1))
                    end_time = float(m.group(2))
                    mb = float(m.group(5))
                    jitter = float(m.group(6))
                    latency_avg = float(m.group(10))
                    records.append({
                        "Multicast Group": group_ip,
                        "Receiver Host": host,
                        "Start Time (s)": start_time,
                        "End Time (s)": end_time,
                        "Bandwidth (Mbps)": mb,
                        "Jitter (ms)": round(jitter, 3),
                        "Latency Avg (ms)": round(latency_avg, 3)
                    })

    df = pd.DataFrame(records)
    print(df.columns)
    print(df.head())
    df.sort_values(by=["Multicast Group", "Receiver Host", "Start Time (s)"], inplace=True)

    # 匯出 CSV
    df.to_csv(f"{tmp_dir}/{file_name}", index=False)
    print(f"✅ Saved to {file_name}")

    return f"{tmp_dir}/{file_name}"

def generate_result_graph(result_path, csv_file):
    df = pd.read_csv(csv_file)
    df = df.rename(columns={"Bandwidth (Mbps)": "Throughput (Mbps)"})

    required_columns = {"Multicast Group", "Receiver Host", "Start Time (s)", "Throughput (Mbps)", "Jitter (ms)", "Latency Avg (ms)"}
    if not required_columns.issubset(df.columns):
        raise ValueError(f"Missing columns: {required_columns - set(df.columns)}")

    # 聚合處理
    agg_df = df.groupby(["Multicast Group", "Receiver Host", "Start Time (s)"], as_index=False).agg({
        "Throughput (Mbps)": "sum",
        "Jitter (ms)": "mean",
        "Latency Avg (ms)": "mean"
    })

    # 過濾掉第 0 秒
    agg_df = agg_df[agg_df["Start Time (s)"] > 0]
    agg_df = agg_df[agg_df["Start Time (s)"] < 61]

    # 為每個 multicast group 與 host 畫圖
    unique_pairs = agg_df[["Multicast Group", "Receiver Host"]].drop_duplicates()

    for (group_ip, host) in unique_pairs.itertuples(index=False):
        subset = agg_df[(agg_df["Multicast Group"] == group_ip) & (agg_df["Receiver Host"] == host)]

        # 畫 throughput
        plt.figure(figsize=(12, 5))
        plt.plot(subset["Start Time (s)"], subset["Throughput (Mbps)"], label="Throughput (Mbps)", marker="o")
        plt.title(f"Throughput Over Time - {group_ip} to {host}")
        plt.xlabel("Start Time (s)")
        plt.ylabel("Throughput (Mbps)")
        plt.ylim(0,30)
        plt.grid(True)
        plt.tight_layout()
        safe_name = f"throughput_{group_ip.replace(':', '_')}_{host}.png"
        plt.savefig(os.path.join(result_path, safe_name))
        plt.close()

        # 畫 jitter
        plt.figure(figsize=(12, 5))
        plt.plot(subset["Start Time (s)"], subset["Jitter (ms)"], label="Jitter (ms)", marker="x", color="orange")
        plt.title(f"Jitter Over Time - {group_ip} to {host}")
        plt.xlabel("Start Time (s)")
        plt.ylabel("Jitter (ms)")
        plt.ylim(bottom=0)
        plt.grid(True)
        plt.tight_layout()
        safe_name = f"jitter_{group_ip.replace(':', '_')}_{host}.png"
        plt.savefig(os.path.join(result_path, safe_name))
        plt.close()

        # 畫 latency
        plt.figure(figsize=(12, 5))
        plt.plot(subset["Start Time (s)"], subset["Latency Avg (ms)"], label="Latency Avg (ms)", marker="x", color="pink")
        plt.title(f"Latency Over Time - {group_ip} to {host}")
        plt.xlabel("Start Time (s)")
        plt.ylabel("Latency Avg (ms)")
        plt.ylim(bottom=0)
        plt.grid(True)
        plt.tight_layout()
        safe_name = f"latency_{group_ip.replace(':', '_')}_{host}.png"
        plt.savefig(os.path.join(result_path, safe_name))
        plt.close()

    print(f"✅ 所有圖表已儲存於 `{result_path}` 資料夾中")

def move_folder_contents(source_dir, target_dir):
    # 確保目標資料夾存在
    os.makedirs(target_dir, exist_ok=True)

    for item in os.listdir(source_dir):
        src_path = os.path.join(source_dir, item)
        dst_path = os.path.join(target_dir, item)

        # 使用 shutil.move 搬移（可以搬檔案或資料夾）
        shutil.move(src_path, dst_path)

    print(f"[✅] Moved all contents from {source_dir} → {target_dir}")


if __name__ == "__main__":
    csv_file = raw_data_analysis(tmp_dir)
    result_dir = create_incremental_result_dir()
    generate_result_graph(result_dir, csv_file)
    move_folder_contents(raw_data_dir, f"{result_dir}/raw_data")


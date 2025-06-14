#!/bin/bash
set -e

# === 系統依賴 ===
echo ✅ Updating system and installing dependencies...
sudo apt update
sudo apt install -y git curl build-essential libssl-dev zlib1g-dev \
     libbz2-dev libreadline-dev libsqlite3-dev wget llvm \
     libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
     libffi-dev liblzma-dev python3-pip python3-openssl openvswitch-switch \
     libnfnetlink-dev libnetfilter-queue-dev python-is-python3

# === 安裝 pyenv（如尚未存在） ===
if ! command -v pyenv &> /dev/null; then
  echo ✅ Installing pyenv...
  curl https://pyenv.run | bash

  # 寫入 .bashrc，供未來 shell 使用
  echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
  echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
  echo 'eval "$(pyenv init --path)"' >> ~/.bashrc
  echo 'eval "$(pyenv init -)"' >> ~/.bashrc
  echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
fi

# === 立即套用 pyenv 至目前 shell ===
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

# === 安裝 Python 3.9.13 與 virtualenv ===
if ! pyenv versions --bare | grep -q "^3.9.13$"; then
  pyenv install 3.9.13
fi
if ! pyenv virtualenvs --bare | grep -q "^ryu-env$"; then
  pyenv virtualenv 3.9.13 ryu-env
fi

# 設定當前目錄使用 ryu-env
pyenv local ryu-env

# === 設定 VS Code 預設 interpreter ===
mkdir -p .vscode
cat > .vscode/settings.json <<EOF
{
  "python.pythonPath": "$PYENV_ROOT/versions/3.9.13/envs/ryu-env/bin/python"
}
EOF
echo ✅ VS Code Python interpreter set to ryu-env

# === 安裝 Python 相依套件 ===
pip install --upgrade pip
pip install "setuptools<58" wheel networkx paramiko \
    netfilterqueue scapy pyqt5 flask pandas matplotlib \
    pulp

# === 安裝 netfilterqueue 與 scapy (需使用 sudo 安裝至系統層級避免編譯錯誤) ===
echo ✅ Installing netfilterqueue and scapy to system site-packages...
sudo pip install netfilterqueue scapy

# === 安裝 Ryu ===
mkdir -p external

if [ ! -d external/ryu ]; then
  git clone https://github.com/faucetsdn/ryu.git external/ryu
fi
cd external/ryu
pip install --no-build-isolation --no-use-pep517 -e .  # ⬆ editable mode 從原始碼直接執行
cd ../..
echo ✅ Ryu linked to: $(python -c "import ryu; print(ryu.__file__)")

# === 儲存 Python 相依套件清單 ===
pip freeze > requirements.txtS

# === 將 ryu_controller 目錄加入 PYTHONPATH 使 Python 可直接 import ===
mkdir -p ryu_controller
RYU_PATH="$(pwd)/ryu_controller"
export PYTHONPATH="$RYU_PATH:$PYTHONPATH"
echo "export PYTHONPATH=\"$RYU_PATH:\$PYTHONPATH\"" >> ~/.bashrc

echo ✅ VS Code Python interpreter set to ryu-env

# === 安裝 Mininet ===
if [ ! -d external/mininet ]; then
  git clone https://github.com/mininet/mininet external/mininet
fi
cd external/mininet
git fetch --tags
git checkout 2.3.1b4 || echo "⚠ checkout 2.3.1b4 failed, using default branch."
sudo ./util/install.sh -a
echo ✅ Mininet version: $(sudo mn --version)
cd ../..


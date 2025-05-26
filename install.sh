#!/bin/bash
set -e

# === 系統依賴 ===
echo ✅ Updating system and installing dependencies...
sudo apt update
sudo apt install -y git curl build-essential libssl-dev zlib1g-dev \
     libbz2-dev libreadline-dev libsqlite3-dev wget llvm \
     libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
     libffi-dev liblzma-dev python3-pip python3-openssl openvswitch-switch

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

# === 安裝 Python 相依套件（確保 setuptools 降版，加入 wheel） ===
pip install --upgrade pip
pip install "setuptools<58" wheel networkx paramiko

# === 刪除舊的 Ryu 安裝資料夾（如存在） ===
rm -rf external/ryu

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
pip freeze > requirements.txt

# === 安裝 Mininet ===
if [ ! -d external/mininet ]; then
  git clone https://github.com/mininet/mininet external/mininet
fi
cd external/mininet
git fetch --tags
git checkout 2.3.0 || echo "⚠ checkout 2.3.0 failed, using default branch."
sudo ./util/install.sh -a
echo ✅ Mininet version: $(sudo mn --version)
cd ../..

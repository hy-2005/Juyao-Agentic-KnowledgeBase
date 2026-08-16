#!/bin/bash
# 双模型组·同文件双实例部署（用户定稿方案）：
#   在 swarp_config_amd.yaml 里为 bge 补两份 -card 后缀的第二实例（同一 llama-swap，
#   不同模型名 = 独立 llama-server 进程，各 16 并发槽），不新开配置文件/端口。
# 同时撤销先前误建的 bge2 新文件方案（swarp_config_amd_bge2.yaml + compose bge2 服务）。
# 用法：在服务器上以 root 执行（或挂载宿主根运行，见下方 docker run 备选）。
# 生成于 2026-08-16；模型块自原配置 awk 抽取复制，cmd 路径/GGUF 复用不变。

set -e
CONF_DIR=/home/cube/cube-home/cube-llm/cube-conf
SRC=$CONF_DIR/swarp_config_amd.yaml
COMP=/home/cube/cube-home/cube-llm/docker-compose_amd.yaml

# 0) 前置确认：主配置当前模型数（应 ≥25；若明显偏少说明此前被破坏，先恢复 .bak-*）
echo "== 前置检查 =="
echo "主配置模型条目数（应≥25）: $(grep -c '^  \"[a-zA-Z]' "$SRC")"
ls -la "$SRC"

# 1) 撤销 bge2 新文件方案
rm -f "$CONF_DIR/swarp_config_amd_bge2.yaml"
if grep -q "cube-llm-bge2:" "$COMP"; then
  cp "$COMP.bak-20260816-bge2" "$COMP"
  chown root:root "$COMP" && chmod 644 "$COMP"
  echo "== compose 已回滚到原始版（bge2 服务移除）=="
fi

# 2) 主配置补 -card 双实例（幂等：已存在则跳过）
if grep -q '"bge-m3-Q8_0-card"' "$SRC"; then
  echo "== -card 实例已存在，跳过插入 =="
else
  # 抽取 bge-m3 块(624-648)：首行改名为 -card，跳过 aliases(625-627)，cmd 路径不动
  awk 'NR==624 {print "  \"bge-m3-Q8_0-card\":"; next}
       NR>=625 && NR<=627 {next}
       NR>=624 && NR<=648 {print; next}' "$SRC" > /tmp/card_m3.txt
  # 抽取 reranker 块(649-674)：同理
  awk 'NR==649 {print "  \"bge-reranker-v2-m3-Q8_0-card\":"; next}
       NR>=650 && NR<=652 {next}
       NR>=649 && NR<=674 {print; next}' "$SRC" > /tmp/card_rr.txt
  echo "== 抽取的 -card 块检查 =="
  grep -c '"bge-m3-Q8_0-card"\|"bge-reranker-v2-m3-Q8_0-card"' /tmp/card_m3.txt /tmp/card_rr.txt
  grep -- '--model' /tmp/card_m3.txt /tmp/card_rr.txt

  # 单次 awk 在锚点行后插入两块（行号只读原文件，无位移问题）
  awk -v f1=/tmp/card_m3.txt -v f2=/tmp/card_rr.txt '
    NR==648 {print; while ((getline l < f1) > 0) print l; next}
    NR==674 {print; while ((getline l < f2) > 0) print l; next}
    {print}' "$SRC" > /tmp/new_main.yaml
  cp "$SRC" "$SRC.bak-20260816-card"
  mv /tmp/new_main.yaml "$SRC"
  chown root:root "$SRC" && chmod 644 "$SRC"
  echo "== 主配置已补 -card 双实例（备份: swarp_config_amd.yaml.bak-20260816-card）=="
fi

# 3) 校验
echo "== 校验 =="
python3 -c "import yaml; yaml.safe_load(open('$SRC')); print('主配置 YAML OK')"
grep -n 'bge-m3-Q8_0-card\|bge-reranker-v2-m3-Q8_0-card' "$SRC" | head -6
cd /home/cube/cube-home/cube-llm && docker compose -f docker-compose_amd.yaml config -q && echo "compose OK"

# 4) 重启主服务使配置生效（11435 会短暂中断几秒）
echo "== 重启 cube-llm =="
docker compose -f docker-compose_amd.yaml up -d cube-llm
sleep 8

# 5) 验证 -card 模型可见
echo "== 验证 =="
curl -s http://127.0.0.1:11435/v1/models | grep -o '"id":"[^"]*"' | grep -i bge

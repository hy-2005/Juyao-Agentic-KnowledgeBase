# 将 RAG 文档 topic 设为 3 分区（与 application.yml listener-concurrency: 3 对齐）。
# 已有 topic 用 --alter；不存在则 --create。
# 用法: .\scripts\kafka-init-rag-topic.ps1

$ErrorActionPreference = "Stop"
$Topic = "juyao.rag.documents"
$Partitions = 3
$Bootstrap = if ($env:SPRING_KAFKA_BOOTSTRAP_SERVERS) { $env:SPRING_KAFKA_BOOTSTRAP_SERVERS } else { "127.0.0.1:9092" }
$Container = if ($env:KAFKA_CONTAINER) { $env:KAFKA_CONTAINER } else { "juyao-kafka" }

Write-Host "Kafka topic=$Topic partitions=$Partitions bootstrap=$Bootstrap"

$exists = docker exec $Container kafka-topics --bootstrap-server localhost:9092 --list 2>$null | Select-String -Pattern "^$([regex]::Escape($Topic))$"
if ($exists) {
    Write-Host "Altering existing topic ..."
    docker exec $Container kafka-topics --bootstrap-server localhost:9092 `
        --alter --topic $Topic --partitions $Partitions
} else {
    Write-Host "Creating topic ..."
    docker exec $Container kafka-topics --bootstrap-server localhost:9092 `
        --create --topic $Topic --partitions $Partitions --replication-factor 1
}

docker exec $Container kafka-topics --bootstrap-server localhost:9092 --describe --topic $Topic
Write-Host "Done."

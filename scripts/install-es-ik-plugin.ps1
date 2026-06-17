# 下载并安装与 docker-compose 中 ES 版本匹配的 IK 分词器到 es_plugins/analysis-ik
# 用法: .\scripts\install-es-ik-plugin.ps1
# 版本须与 docker-compose.yml 中 juyao-es 镜像 tag 一致

$ErrorActionPreference = "Stop"
$EsVersion = "7.17.18"
$Root = Split-Path -Parent $PSScriptRoot
$Base = Join-Path $Root "es_plugins"
$PluginDir = Join-Path $Base "analysis-ik"
$ZipUrl = "https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-$EsVersion.zip"
$ZipFile = Join-Path $Base "elasticsearch-analysis-ik-$EsVersion.zip"

New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
Write-Host "Downloading IK plugin for ES $EsVersion ..."
Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipFile -UseBasicParsing
Write-Host "Extracting to $PluginDir ..."
if (Test-Path $PluginDir) { Remove-Item $PluginDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
Expand-Archive -Path $ZipFile -DestinationPath $PluginDir -Force
Remove-Item $ZipFile
Write-Host "Done. Restart ES: docker compose up -d juyao-es"

from modelscope import snapshot_download

# 下载模型到本地目录
model_dir = snapshot_download(
    'Xorcodes/bge-m3',  # ModelScope上的模型ID
    cache_dir='/root/LawAgent/models',
    local_dir='/root/models/bge-m3-local'
)

print(f"模型已下载到: {model_dir}")

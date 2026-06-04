from modelscope import snapshot_download

print("开始从国内镜像下载 BGE-M3...")
snapshot_download(
    model_id='Xorbits/bge-m3', # 魔搭上的同步ID
    cache_dir='/root/agent/models/bge-m3'   # 存放目录
)

print("开始从国内镜像下载 Cross-Encoder...")
snapshot_download(
    model_id='BAAI/bge-reranker-v2-m3', 
    cache_dir='/root/agent/models/bge-reranker-v2-m3'
)

print("全部下载完成！")



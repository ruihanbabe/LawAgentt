工业级开发的数据schema:
payload里不存Dense、Sparse 还是 ColBERT
存储成本大、网络传输慢影响带宽、查询性能受影响(qdrant里对向量有专门的索引和存储格式, 比payload过滤快)、功能限制(payload里存了向量做不了相似度搜索, 只能做精确匹配或范围过滤)
dense、sparse和colbert通过专门的api存储和检索;
工业界标准做法是qdrant只返回id+相似度分数+payload指定字段
对于rerank等需要向量的需求, 用id去向量存储里取, 或者用payload文本重新计算;

工业级RAG检索:
先用基于语义相似度的dense和基于关键词匹配的sparse初筛, 百万级数据做初排;
然后对两个结果集合并去重, 用RRF等算法合并排序, 取topN
最后对N个文本用colbert做rerank, 计算query和N个文档精细化交互分数
性能瓶颈：ColBERT 需要计算查询和每个文档 token 之间的注意力，计算量是 Dense 的几十倍。如果直接在百万级数据上跑，响应时间会是分钟级，用户体验无法接受。
资源限制：ColBERT 推理需要大量 GPU 内存，并发查询会迅速耗尽资源。
精度边际递减：在 Dense/Sparse 召回的 Top50 候选上做 ColBERT Rerank，已经能获得接近全局搜索最优的结果，没必要在全量数据上跑

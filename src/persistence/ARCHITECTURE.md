# Persistence 模块

负责会话、画像和 Trace 的 repository contract、TTL、删除及事务语义。数据库产品不得定义业务规则，所有 Adapter 必须服从端口契约。端口、内存实现和 Adapter 均位于本目录。

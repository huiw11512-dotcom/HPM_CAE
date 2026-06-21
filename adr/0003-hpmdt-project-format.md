# ADR 0003: hpmdt Project Format

状态：Accepted

## 决策

Studio 工程采用 `*.hpmdt` ZIP 容器，包含 manifest、scene、missions、solvers、probes、results 和 metadata。

## 原因

ZIP 容器易于保存 JSON 语义、GLB 视觉资产和结果索引，同时保持工程可迁移、可审计、可版本迁移。

## 后果

旧 YAML 工程通过迁移器导入。旧输出目录不进入新工程格式。

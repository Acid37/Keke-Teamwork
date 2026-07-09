## 摘要

- 新增后端只读并行 researcher 编排雏形。
- researcher 子任务继续走只读委派路径。
- 补充并发执行、单 worker 超时和默认 researcher 调度测试。

## 测试

- [ ] `python -m unittest -v`

## 安全边界

- researcher worker 只允许 read/search/list 工具。
- 当前版本不启用自动文件写入、编辑或命令执行。

## 备注

- 最终结果合并和 UI 接入留到后续变更。

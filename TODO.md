# 待办

## [ ] 加入 HACS 默认列表

把 `prismatechcode/ha-mcp-for-qixu` 按字母顺序写入 [hacs/default](https://github.com/hacs/default) 的 `integration` 文件，并提交 PR。

当前状态：仓库已公开，`v0.1.0` 已发，HACS Action / hassfest 已通过；用户只能通过 **HACS → 自定义存储库** 安装，尚未进入默认列表。

### 加入默认列表的好处

- **安装更简单**：用户在 HACS 里直接搜「栖序 / qixu」就能装，不用自己填仓库地址
- **更容易被发现**：出现在默认目录里，自然安装量和曝光会高于自定义仓库
- **信任感更强**：对集成商和普通用户更像正规、可维护的插件
- **更新体验不变**：版本仍由本仓库的 GitHub Release 驱动，和已收录插件一致

### 代价与注意

- 需向 `hacs/default` 提 PR，审核可能要几个月
- 收录后对发版、维护、仓库质量的要求更固定
- 内测 / 公测阶段用自定义仓库即可；扩大自然安装量时再冲默认列表

### 参考

- 收录说明：https://hacs.xyz/docs/publish/include

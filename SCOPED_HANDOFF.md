# 日志授权复核

厂内全版交接沿用 README.md。外部复核以一个已经冻结的日版为起点。档案员在任何授权办理前固定该版的锚，之后的不同授权共用这个锚。异地仓通过可信的独立渠道取得锚和授权，再验实际收到的运输件。运输件可以被截改、删行或整件替换，验收仍以独立收到的两项资料为准。

## 调用方式

连接与事务沿用 README.md。下列三个源仓入口位于 `lake.edition.publish`，异地签存入口位于 `lake.reporting.sign`。

| 调用 | 成功结果 |
| --- | --- |
| `seal_scope(source, revision_id)` | 返回可单独保存的日版锚 `bytes`。锚只携带版身份和该版固定摘要，可附格式版本。相同日版再次调用返回同样的字节，包括重开源库后。 |
| `grant_scope(source, revision_id, device, log, columns)` | 将调用方已批准的一个设备、日志组合及列选择制成授权 `dict`。日版须已有锚。组合在该版确无观测也可授权。 |
| `issue_scoped(source, grant)` | 返回可搬运的 UTF-8 JSON `bytes`。 |
| `reconcile_scoped(remote, anchor, grant, raw)` | 只用异地库、另收的锚和授权及实际运输字节核验。成功返回已签报告，可用 `lake.reporting.retrieve.retrieve(remote, report_id)` 复领。 |

授权有 `revision_id`、`device`、`log`、`columns`、`selector` 五项。设备及日志名沿用出处的非空文本规则，必须同时精确匹配。列沿用 V1 的非空、无重复选择，授权以列表保存列名顺序。`selector` 为绑定该版组合的不透明非空字符串。授权不带应到行、行数或本单摘要。调用方职责是传递经批准的授权以及先行保存的锚。工程内无需另设审批服务。

## 出件与签存

运输件是含 `rows` 数组和 `proof` 值的 JSON 对象。每个 `rows` 元素沿用报告明细的 `reference`、`provenance` 和 `values`，其中 `values` 恰有获准列。`proof` 的表示由实现决定。运输和证明可附不透明的核验材料。不得附完整原行册、范围外的原测次或出处、未授权列的值或其开封材料。新增证据不得让受领方凭候选原值直接核对隐藏内容。已有 `revision_id` 仍为双方通用的日版标识。列值类型和空值语义沿用 V1。

异地仓须核实授权适用于该锚的确切日版，文件中匹配原测次全部且仅出现一次，顺序、出处及获准列与冻结时相符。缺少授权列与收到已证为空的列值有不同结果。无匹配的组合凭完整证据可签零行。少证、漏行、重行、乱序、改值、越权或串版抛 `ValueError`，报告目录保持原状。源端未知日版或申请未封存的锚时抛 `LookupError`，非法参数抛 `ValueError`。

报告沿用原报告的 `report_id`、`revision_id`、`columns`、`rows`、`row_count` 和 `non_null`，另以 `scope` 返回本次授权字典。授权、明细及计数一并提交，重开远端后按原入口复领相同内容。原厂内报告和旧材料仍可按原接口处理。

## 交接样例

`scope_fixture.load_case()` 读取 `samples/scoped_kiln.json`，`populate(source, case)` 沿 V1 接纳、登记意见与冻结。`trusted_inputs(anchor, grant)` 仅将两项可信输入单独复制给异地调用方。用 `python3 -B scope_fixture.py` 可查看现有全版发行携带的原行册范围。

对 `collector-2` 的 `out.log` 只授权 `reading` 时，签存批内第 1、3、4 次，读值依序为 `7, null, 7`，`row_count` 为 3，`non_null` 为 `{"reading": 2}`。第 1 次和第 4 次拥有相同读值与出处，引用各归原测次。第 2 次的内检出处和所有未授权列留在源仓。删掉第 3 次、用第 2 次替换第 4 次、交换外送行顺序或送来另一日版的原件，应在报告写入前拒绝。也用这一锚授权 `absent.log`，齐证时签零行，去掉证明时拒签。可在另一份样例将外送组的读值改为空，核对匹配的三行仍全部入账且非空数为零。

## 运行

沿用现有 `.pointwise-runtime.json` 的版本 1 CLI 清单。`setup` 记录准备步骤的参数数组列表，`verify` 和 `demo` 各记录一条命令的参数数组。核验须实际运行原完整回归并检查上述交接，业务不符时以非零状态退出。演示须实际发行，关闭源库后验真件与改件，并重开异地仓按报告号领取原明细及计数。原演示入口继续可用。

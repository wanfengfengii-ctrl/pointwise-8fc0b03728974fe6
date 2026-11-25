# 海岬排放观测湖

海岬建材厂由白班登记窑线采集器的观测，质控员标注意见，档案员冻结日版并按列送件。夜班关闭源库后核对观测值和质控，按设备日志出处回查，保管员重开后凭报告号交付原结果。

需要 Python 3.11，仅使用标准库。在项目根目录运行。

```sh
python3 -B check_project.py
python3 -B demo.py
```

回归入口由运行平台物化。也可在项目根目录用 `python3 -B -m unittest discover` 直接运行完整测试。演示在临时目录建立两库及交接文件，按反序送件，补件前查待件，补件后签存并重开异地库复领。样例中甲、乙、丙是 K2 批内第 1、2、3 次，分别交付 7/通过、空/复核、7/剔除。读值非空数为 2，质控非空数为 3。

## Python API

- `lake.storage.open_source(path)` 和 `lake.storage.open_remote(path)` 打开或初始化 SQLite 库。调用方负责关闭连接。重开保留业务记录，初始化不导入样例。写入口各自提交，调用时连接应处于空闲事务状态。
- `lake.intake.batches.ingest(source, site, day, batch, records)` 返回原测次引用元组。`day` 使用 `YYYY-MM-DD`。按设备顺序提供记录，每条有 `reading`、`provenance`，可选 `temperature`。出处字段为 `device`、`log`、`line`、`unit`，日志行号及测次序从 1 开始。读值、温度是精确整数或 `None`，温度单位是摄氏度，读值保留出处中的申报单位。缺省温度等同空温度。非法批或同号异件抛出 `ValueError`，同号同内容重投返回原引用。站日原序取批次首次实收顺序再取批内序。
- `lake.quality.amendments.amend(source, ref, status, author)` 登记 `通过`、`复核` 或 `剔除`，返回具有 `amendment_id` 的具名记录。未知测次抛出 `LookupError`，非法意见抛出 `ValueError`。`load_amendment` 可按号查询。
- `lake.quality.freeze.freeze_day(source, site, day, amendment_ids=())` 按选定意见冻结并返回 `DayRevision`，包含 `revision_id` 与原序 `rows`。对同一测次采用所选意见中登记最晚的一条。空站日可冻结。未知意见抛出 `LookupError`，外站日意见抛出 `ValueError`。`lake.quality.revisions.load_revision` 按号读原版。
- `lake.edition.publish.issue(source, revision_id, columns)` 返回具有 `issue_id` 和 `materials` 的 `Issue`。列名为 `reading`、`quality`、`temperature`，领件时提供非空且无重复的名称列表或元组。不存在的日版抛出 `LookupError`，非法选择抛出 `ValueError`。`lake.edition.issued.load_issued_materials` 原样补取已提交发行，`materials` 是可独立搬运的 UTF-8 JSON 字节串元组。
- `lake.receiving.accept.receive(remote, raw)` 验收一个原件并返回整数实收号。`lake.receiving.ledger.list_issue_receipts(remote, revision_id, issue_id)` 查询该发行的实收号。重投同身份同核定内容复用原号，坏件抛出 `ValueError`，同身份异件抛出 `MaterialConflict`。
- `lake.reporting.sign.reconcile_columns(remote, revision_id, receipt_ids, columns)` 签出 `SignedReport`。每行包含 `reference`、`provenance` 和 `values`。结果保留原序，`row_count` 取原行数，`non_null` 分别统计各列，零值和重复值按各自测次计入。缺件抛出 `PendingMaterials`，矛盾抛出 `MaterialConflict`，未知实收号抛出 `LookupError`。SQLite 写入错误沿原错误抛出。失败不产生报告号。`lake.reporting.retrieve.retrieve(remote, report_id)` 按号读取原成果，未知号抛出 `LookupError`。

## 交接及核账口径

V1 件具有 `version`、`revision_id`、`issue_id`、`kind`、`body` 和 `digest`。内容标识是去掉 `digest` 后规范 JSON 的 SHA-256，规范 JSON 使用 ASCII 转义、键排序及紧凑分隔。`volume` 正文含列名、物理卷号和本卷实值。数值按值及原序排序，质控按剔除、通过、复核及原序排序。读值每卷一项，质控和温度每卷最多两项。`row_register` 保全原序测次与出处，`column_basis` 引用原行册正文标识并记录各卷标识、卷内行号与确证空行号。行号从 1 开始，指该原行册中的原测次。

合读只使用请求引入的已验实收件。卷和对应列据在同一日版及发行内配对。每个所选列都要由一个发行完整供数，不能用不同发行的半列拼齐。同日版可从各自齐备的发行选取不同列，原行册正文须一致。当前日版已实收的共同原行册可以支持指向其正文标识的列据。未选列欠件不影响结清。全空列须实收列据并覆盖全部原行，此时预期实物卷数为零。剔除是原测次的质控意见，核账明细依然包含该行。完整明细和计数与报告号一并提交，后续源更正不改变已经签存的结果。

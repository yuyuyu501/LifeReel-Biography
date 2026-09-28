# 支付宝扫码收款与小程序支付边界

更新日期：2026-09-28。

## 本次实现

- Web 使用部署目录中的支付宝静态收款码；页面展示配置的收款方和账号。
- 付款人需要在支付宝中填写页面显示的金额，当前单笔范围为 0.01–200 元。
- 这是人工核实收款：创建订单、显示二维码、提交付款声明、浏览器轮询均不会增加余额。仅服务器操作员核对真实收款账单后入账。
- 微信仅作为禁用占位；即使遗留 `MANUAL_WECHAT_ENABLED=true`，本版本也不接受新微信充值。历史微信订单仍可查询、核实、退款争议排查，不能重新展示支付宝二维码。
- 微信和抖音小程序仅显示本平台支付暂未开放，不展示外部收款码、不伪造支付跳转或回调。
- 充值记录仍只展示已核实入账的记录，消费明细仍只展示消费。

## 生产配置

以下配置保存在私有 `.env`，不提交 Git：

```dotenv
MANUAL_ALIPAY_ENABLED=true
MANUAL_ALIPAY_QR_PATH=/data/payments/alipay-qr.png
MANUAL_ALIPAY_RECIPIENT_NAME=<收款主体全称>
MANUAL_ALIPAY_RECIPIENT_ACCOUNT=<收款账号>
MANUAL_WECHAT_ENABLED=false
```

收款码存放于宿主机 `data/payments/alipay-qr.png`，通过已有只读挂载供 API 使用。缺少开关、图片、收款名称或账号任一项时，充值自动禁用。图片和支付配置不可打包到前端、Git 或公开静态资源目录。收款方信息由经营者提供；二维码离线解码不能证明实际支付宝账户的实名认证主体。上线后的首笔人工验收必须核对支付宝实际显示的收款方。

二维码 API 需要登录和当前租户的待付款支付宝订单 ID，响应不缓存。收款渠道切换不能把旧微信订单展示成支付宝订单。迁移 `20260928_0035` 将历史订单标记为微信，新业务明确写入支付宝。

## 人工核实入账

查看订单：

```sh
docker compose -f compose.production.yaml exec -T api python -m lifereel_api.modules.billing.recharge_admin list
```

在收款方支付宝账单中核对付款渠道、实收金额、交易号和付款人；需要根据付款人提供的付款凭证及其平台账号确认对应租户和订单。**不能仅凭金额、付款时间接近或付款人声明匹配订单。**当前页面不自动采集付款凭证，请经营者与付款人直接核对。确认后执行：

```sh
docker compose -f compose.production.yaml exec -T api python -m lifereel_api.modules.billing.recharge_admin confirm --order-id <订单UUID> --operator <操作员标识> --amount-cents <实际收款分数> --payment-transaction <真实交易号> --received
```

`--received` 是操作员已核实的声明，并非系统查询支付宝的结果。确认会写入一次钱包账本；重复确认同一订单幂等，同一真实交易号不能用于重复入账。金额不一致会拒绝确认。未确认收款前，不要直接修改数据库钱包余额。拒绝操作可用 `reject --order-id ... --operator ... --reason ...`。

## 小程序不是任意 App 跳转

2026-09-28 核对的官方文档：

- 微信 `wx.requestPayment`：https://developers.weixin.qq.com/miniprogram/dev/api/payment/wx.requestPayment.html 。需要在小程序平台申请微信支付，服务端下单后得到 `prepay_id` 并签名，再在微信内调起支付；不是把支付宝收款账号写入一个跳转链接。
- 抖音 `tt.pay`：https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/api/open-interface/pay/tt-pay 。文档要求商户入驻、服务端生成订单后调用平台收银台，列出微信支付和支付宝，最终状态以商户后端结果为准；`success` 被调用本身不等于付款成功。
- 同一抖音文档注明 iOS 虚拟物品支付限制。AI 服务/钱包充值实际可接入类目、终端和交易产品，须以该小程序商户审核和控制台可用能力为准，不承诺所有终端都能充值。

两个小程序要开放正式支付，需补齐各自 AppID/商户资质/交易产品权限、服务端密钥或证书、签名验签、支付通知、查单补偿、退款和对账。只有静态二维码和支付宝账号不能实现这套自动入账。

## 测试与验收边界

- 自动回归使用隔离数据库、假支付凭证和 mock，不调用真实支付接口。
- 覆盖开关/缺配置关闭、微信禁用、租户隔离、二维码订单绑定、旧微信订单、金额校验、幂等/防重复入账、页面轮询和错误提示。
- PostgreSQL 验证包含历史版本升级、历史渠道回填、模型一致性检查。
- 离线验证所提供二维码与裁剪后的图片解码内容一致，实际支付宝扫码识别、收款方核对、一笔真实小额付款和人工核实到账仍须人工验收。
- 不把小程序编译成功称作真机支付成功；当前小程序支付明确禁用。

# BID 组合有效性规则 — P0 硬约束

违反以下任何一条 → BID 无效，必须重新推断。

---

## P0-01: CORE·PI 与 CL·PI 必须一致

❌ CORE·PI=0101, CL·PI=0203
✅ CORE·PI=0101, CL·PI=0101
✅ CORE·PI=00, CL·PI=00

## P0-02: CL·SUB=00 时 CR 不能为 03（子集群页）

❌ SUB=00, CR=03
✅ SUB=00, CR=02
✅ SUB=A1, CR=03

## P0-03: CL·PI=00 时 SUB/CR/IL/LT/PF 全部失效

❌ PI=00, SUB=A1, CR=02
✅ PI=00 → CL 层标记 N/A

## P0-04: CR=01（支柱页）强制要求 GC=02 + DP≥03

❌ CR=01, GC=01, DP=02
✅ CR=01, GC=02, DP=04

## P0-05: GI=05（洞见源）强制要求 SO=01 + TN=04

❌ GI=05, SO=02, TN=02
✅ GI=05, SO=01, TN=04

## P0-06: ST 模板与 CT 体裁不兼容组合

❌ ST=01(步骤指南) + CT=05(参考/百科)
❌ ST=04(对比评测) + CT=05(参考/百科)
❌ ST=05(研究报告) + CT=02(列表)
✅ 其余组合均允许

## P0-07: OBJ=01（流量获取）时 CI 不能为 03（强 CTA）

❌ OBJ=01, CI=03
✅ OBJ=01, CI=01
✅ OBJ=03, CI=03

## P0-08: JS=01（认知阶段）时 SI 不能为 04（商业/交易意图）

❌ JS=01, SI=04
✅ JS=01, SI=03
✅ JS=03, SI=04

## P0-09: AL=01（零基础）+ KL=01（Head 词）+ DP=04（极深）三方矛盾

❌ AL=01, KL=01, DP=04
✅ AL=01, KL=01, DP=02
✅ AL=04, KL=01, DP=04

## P0-10: IC=02（NoIndex）时 SEO/GEO 层全部点位降级为 N/A

SEO·SI/QS/KL/KC/SF/SC → N/A
GEO·全部点位 → N/A
CL 层仍有效（站内管理用途）

# Case 4 — New acquisition rebuilds the local TDB (wwybsj-build)

- **Scenario:** 3
- **Status:** ✅ READY (number changed from 466 → 472, see below)
- **Runtime:** before-query ~30 s · build ~2 min · after-query ~60 s
- **Screen:** chat at `/`

## What this proves

A one-line accession record does not just get stored — it gets *related*. The
build writes registration facts (L0), aligns material and period terms against
the existing ontology (L1), and links the new object to the remote archaeology
knowledge base. Then a question no one could answer 3 minutes ago has an answer
with provenance.

## Talk track (preview card)

> The museum just accessioned one object. I'll type it in as raw fields — no
> curation, no essay. The build aligns its material and dating vocabulary to the
> ontology the other 465 objects already share, so the new piece arrives already
> connected. Then I'll ask what it *means*, which is a question about
> relationships, not about the row we just inserted.

## ⚠️ Number changed: 466 → 472

The scenario doc scripts item **466**. That number is already taken in the live
TDB — `辽白釉刻花碗（藏品总登记号 0466）`, left behind by a rehearsal, along with
467, 468, 470, 471, 480, 490, 500, 520. The clean baseline is 1–465.

**472 is verified free** (as are 469, 473–476, 600, 666). If you re-rehearse this
case before the demo, burn a different number each time and update this file —
a "before" state that already exists destroys the case.

## Step 1 — before (prove absence)

```
第472号展品是什么？
```

Expect: not found / no such registration number.

## Step 2 — the accession (paste verbatim)

```
给wwybsj展品录入新展品，信息如下：{ "ww_bh_leixing": "藏品总登记号", "ww_bianhao": "472", "ww_mingchen": "唐鎏金舞马衔杯纹银壶", "ww_yuanming": "舞马衔杯银壶", "ww_niandai_a": "中国历史学年代", "ww_niandai_b": "唐(618~907)", "ww_niandai_c": "盛唐", "ww_niandai_d": "", "ww_niandai_jt": "约公元8世纪", "ww_leibie": "金银器", "ww_zhidi_a": "复合质地", "ww_zhidi_b": "无机质", "ww_zhidi_c": "银、金", "ww_shuliang": 1, "ww_chang": "0.00", "ww_kuan": "0.00", "ww_gao": "14.80", "ww_chicun": "高14.8厘米 口径2.3厘米", "ww_zhiliang_fw": "0-1 kg", "ww_zhiliang_jt": "0.549", "ww_zhiliang_dw": "kg", "ww_jibie": "一级", "ww_laiyuan": "1970年陕西省西安市何家村唐代窖藏出土", "ww_wancan_cd": "完整", "ww_wancan_zk": "壶身鎏金舞马纹清晰，提梁与壶盖以银链相连", "ww_baocun_zt": "状态稳定，不需修复", "ww_baocun_sj": "", "ww_baocun_nd": 0, "ww_zuoze": "", "ww_banben": "", "ww_cunjuan": "", "ww_mingchen_en": "Tang Gilt Silver Flask with Dancing Horse Motif", "ww_ctime": "2026-09-02 10:00:00", "ww_mtime": "0000-00-00 00:00:00" }
```

Watch for, in the trace: routing to **Wwybsj-Build-TDB-Agent**, then
`tdb-wwybsj-build` reporting `写入 N 条登记事实` (L0) and `完成术语对齐` (L1).

## Step 3 — after (prove new relations)

```
第472号展品的文化价值是什么？
```

The answer should reach past the fields we typed — Tang metalwork, the 何家村
hoard, horse motifs — i.e. material that came from the *remote* archaeology KB
via the terms the build just aligned.

## Verified

Proven run of this exact shape, item 0520 `唐镶金兽首玛瑙杯`, completed in 121 s
with 26 L0 facts and term alignment:
`/?run_id=91f28a01-2205-4efd-8647-bc146abae137`

## Fallback

If the live build stalls, open the 0520 run above and narrate it, then query
`第520号展品的文化价值是什么？` — that data is already in the TDB.

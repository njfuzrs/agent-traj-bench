#!/usr/bin/env python3
"""Phase 1 W3: 语义去重 — 文本指纹 + TF-IDF 余弦相似度 + 并查集分组

由于代理不支持 embedding 模型，改用 TF-IDF + jieba 分词做本地语义相似度计算。
对中文短文本（user_query）效果足够，且零成本、可重复。
"""

import json
import time
import sys
import numpy as np
from pathlib import Path
from collections import Counter, defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import jieba

CANDIDATE_FILE = Path("data/bench-staging/meta/candidate-pool.jsonl")
OUT_DIR = Path("data/bench-staging/meta")
DEDUP_OUT = OUT_DIR / "duplicate-groups.jsonl"

SIMILARITY_THRESHOLD = 0.90


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def load_candidates() -> list[dict]:
    records = []
    with open(CANDIDATE_FILE) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def tokenize_chinese(text: str) -> str:
    """jieba 分词，返回空格分隔的 token 序列"""
    return " ".join(jieba.cut(text))


def step1_text_fingerprint(records: list[dict]) -> tuple[list[dict], dict]:
    """Step 1: SHA256 精确去重 — 相同 query_hash 归为同组"""
    hash_groups = defaultdict(list)
    for r in records:
        qhash = r.get("query_hash", "")
        if not qhash:
            qhash = "empty_" + r["sid"][:8]
        hash_groups[qhash].append(r)

    # 每组取第一条作为代表，其余标记为精确重复
    unique = []
    exact_groups = {}  # hash -> [all sids in group]
    for qhash, group in hash_groups.items():
        unique.append(group[0])
        if len(group) > 1:
            exact_groups[qhash] = [r["sid"] for r in group]

    return unique, exact_groups


def step2_tfidf_vectors(records: list[dict]) -> np.ndarray:
    """Step 2: TF-IDF 向量化 user_query"""
    queries = [r.get("user_query", "") or "empty" for r in records]

    # jieba 分词
    print("  Tokenizing with jieba...")
    tokenized = [tokenize_chinese(q) for q in queries]

    # TF-IDF
    print("  Computing TF-IDF vectors...")
    vectorizer = TfidfVectorizer(
        max_features=10000,
        sublinear_tf=True,
        norm="l2",
    )
    tfidf_matrix = vectorizer.fit_transform(tokenized)
    print(f"  TF-IDF shape: {tfidf_matrix.shape}")

    return tfidf_matrix


def step3_union_find(records: list[dict], tfidf_matrix, threshold: float) -> dict:
    """Step 3: 并查集去重，分块计算余弦相似度"""
    n = len(records)
    uf = UnionFind(n)

    print(f"  Computing pairwise similarities for {n} records (threshold={threshold})...")
    t0 = time.time()

    chunk_size = 200
    merge_count = 0
    for i in range(0, n, chunk_size):
        i_end = min(i + chunk_size, n)
        # 计算 chunk_i 与所有后续记录的相似度
        sim_block = cosine_similarity(tfidf_matrix[i:i_end], tfidf_matrix[i:])

        for local_i in range(i_end - i):
            global_i = i + local_i
            start_j = global_i + 1 - i
            if start_j < 0:
                start_j = 0
            for local_j in range(start_j, sim_block.shape[1]):
                global_j = i + local_j
                if global_j <= global_i:
                    continue
                if sim_block[local_i, local_j] > threshold:
                    uf.union(global_i, global_j)
                    merge_count += 1

        if (i + chunk_size) % 500 < chunk_size:
            elapsed = time.time() - t0
            print(f"    Processed {min(i+chunk_size, n)}/{n}, merges={merge_count}, time={elapsed:.0f}s")

    print(f"  Done in {time.time()-t0:.1f}s, total merges: {merge_count}")

    # 构建 groups
    groups = defaultdict(list)
    for idx in range(n):
        root = uf.find(idx)
        groups[root].append(idx)

    return dict(groups)


def step4_classify_groups(
    records: list[dict],
    groups: dict,
    exact_groups: dict,
) -> list[dict]:
    """Step 4: 合并精确重复组 + 语义组，分类并生成 task_id"""
    # 先把精确重复的 session 合并回来
    sid_to_record = {}
    for r in records:
        sid_to_record[r["sid"]] = r

    # 加载全部候选池记录（含精确重复的）
    all_records = []
    with open(CANDIDATE_FILE) as f:
        for line in f:
            all_records.append(json.loads(line))
    all_sid_to_record = {r["sid"]: r for r in all_records}

    results = []
    task_counter = 0

    for root_idx, member_indices in sorted(groups.items(), key=lambda x: -len(x[1])):
        # 收集语义组内所有 session（含精确重复的）
        all_members = []
        for idx in member_indices:
            r = records[idx]
            all_members.append(r)
            # 找这条记录的精确重复兄弟
            qhash = r.get("query_hash", "")
            if qhash in exact_groups:
                for sid in exact_groups[qhash]:
                    if sid != r["sid"] and sid in all_sid_to_record:
                        all_members.append(all_sid_to_record[sid])

        # 去重（同一个 sid 可能被加多次）
        seen_sids = set()
        unique_members = []
        for m in all_members:
            if m["sid"] not in seen_sids:
                seen_sids.add(m["sid"])
                unique_members.append(m)
        all_members = unique_members

        models_in_group = sorted({m.get("model", "unknown") for m in all_members})
        unique_model_families = sorted({
            m.get("model", "unknown").replace("[1m]", "")
            for m in all_members
        })

        if len(unique_model_families) >= 2:
            priority = "P0_multi_model"
        elif len(all_members) >= 3:
            priority = "P1_repeated"
        else:
            priority = "P2_solo"

        task_counter += 1
        task_id = f"T{task_counter:04d}"

        representative = max(all_members, key=lambda m: len(m.get("user_query", "")))

        result = {
            "task_id": task_id,
            "priority": priority,
            "member_count": len(all_members),
            "models": models_in_group,
            "model_families": unique_model_families,
            "representative_query": representative.get("user_query", "")[:300],
            "representative_sid": representative["sid"],
            "members": [
                {
                    "sid": m["sid"],
                    "model": m.get("model", "unknown"),
                    "steps": m.get("steps", 0),
                    "tool_call_count": m.get("tool_call_count", 0),
                }
                for m in all_members
            ],
        }
        results.append(result)

    return results


def main():
    threshold = SIMILARITY_THRESHOLD
    if "--threshold" in sys.argv:
        idx = sys.argv.index("--threshold")
        threshold = float(sys.argv[idx + 1])

    print("=" * 60)
    print("Phase 1 W3: 语义去重 (TF-IDF + jieba)")
    print(f"Threshold: {threshold}")
    print("=" * 60)

    # 加载候选池
    records = load_candidates()
    print(f"\n候选池: {len(records)} 条")

    # Step 1: 文本指纹去重
    print(f"\n--- Step 1: 文本指纹去重 (SHA256) ---")
    unique_records, exact_groups = step1_text_fingerprint(records)
    exact_dup_count = sum(len(v) - 1 for v in exact_groups.values())
    print(f"  精确重复组: {len(exact_groups)} 组 ({exact_dup_count} 条重复)")
    print(f"  去重后唯一记录: {len(unique_records)} 条")

    # Step 2: TF-IDF
    print(f"\n--- Step 2: TF-IDF 向量化 ---")
    tfidf_matrix = step2_tfidf_vectors(unique_records)

    # Step 3: 并查集去重
    print(f"\n--- Step 3: 并查集去重 ---")
    groups = step3_union_find(unique_records, tfidf_matrix, threshold)
    multi_member_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"  总 groups: {len(groups)}")
    print(f"  多成员 groups: {len(multi_member_groups)}")

    # Step 4: 分类
    print(f"\n--- Step 4: 分类 + task_id 生成 ---")
    task_groups = step4_classify_groups(unique_records, groups, exact_groups)

    # 写输出
    with open(DEDUP_OUT, "w") as f:
        for g in task_groups:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    # 统计
    priority_counts = Counter(g["priority"] for g in task_groups)
    size_dist = Counter()
    for g in task_groups:
        mc = g["member_count"]
        if mc == 1:
            size_dist["1 (solo)"] += 1
        elif mc == 2:
            size_dist["2"] += 1
        elif mc <= 5:
            size_dist["3-5"] += 1
        elif mc <= 10:
            size_dist["6-10"] += 1
        else:
            size_dist["11+"] += 1

    total_trajectories = sum(g["member_count"] for g in task_groups)

    print(f"\n{'='*60}")
    print(f"去重结果汇总")
    print(f"{'='*60}")
    print(f"\n原始候选池: {len(records)} 条 trajectory")
    print(f"语义去重后: {len(task_groups)} 个独立 task")
    print(f"  (覆盖 {total_trajectories} 条 trajectory)")
    print(f"\n优先级分布:")
    for p in ["P0_multi_model", "P1_repeated", "P2_solo"]:
        print(f"  {p}: {priority_counts.get(p, 0)}")
    print(f"\nGroup 大小分布:")
    for size in ["1 (solo)", "2", "3-5", "6-10", "11+"]:
        print(f"  {size}: {size_dist.get(size, 0)}")

    # 多模型 group 的模型组合 TOP 10
    multi_model_groups = [g for g in task_groups if g["priority"] == "P0_multi_model"]
    if multi_model_groups:
        combo_counter = Counter(
            tuple(g["model_families"]) for g in multi_model_groups
        )
        print(f"\n多模型 group 模型组合 TOP 10:")
        for combo, count in combo_counter.most_common(10):
            print(f"  {' + '.join(combo)}: {count}")

    # 打印几个多成员 group 示例
    big_groups = sorted(task_groups, key=lambda g: -g["member_count"])[:5]
    if big_groups and big_groups[0]["member_count"] > 1:
        print(f"\n最大的 5 个 group:")
        for g in big_groups:
            print(f"  {g['task_id']}: {g['member_count']} members, {g['priority']}")
            print(f"    query: {g['representative_query'][:100]}")
            print(f"    models: {g['models']}")


if __name__ == "__main__":
    main()

import argparse
import json
from collections import Counter
from pathlib import Path

from sklearn.tree import export_text

from simulate_world_cup_v2 import (
    DEFAULT_ELO_FILE,
    ROOT,
    STRUCTURE_FILE,
    build_match_model_bundle,
    build_team_profiles,
)


def tree_to_dict(estimator, feature_names, class_names):
    tree = estimator.tree_

    def node_to_dict(node_id):
        left = tree.children_left[node_id]
        right = tree.children_right[node_id]
        value = tree.value[node_id][0]
        samples = int(tree.n_node_samples[node_id])
        weighted_samples = float(tree.weighted_n_node_samples[node_id])
        counts = {class_name: float(value[index]) for index, class_name in enumerate(class_names)}
        predicted_class = max(counts, key=counts.get)
        row = {
            "node": int(node_id),
            "samples": samples,
            "weighted_samples": round(weighted_samples, 4),
            "class_counts": counts,
            "predicted_class": predicted_class,
        }
        if left != right:
            feature = feature_names[tree.feature[node_id]]
            threshold = float(tree.threshold[node_id])
            row.update(
                {
                    "feature": feature,
                    "threshold": round(threshold, 6),
                    "left_if": f"{feature} <= {threshold:.6f}",
                    "right_if": f"{feature} > {threshold:.6f}",
                    "left": node_to_dict(left),
                    "right": node_to_dict(right),
                }
            )
        return row

    return node_to_dict(0)


def tree_summary(estimator, feature_names):
    tree = estimator.tree_
    split_features = [
        feature_names[index]
        for index in tree.feature
        if index >= 0
    ]
    return {
        "nodes": int(tree.node_count),
        "max_depth": int(tree.max_depth),
        "leaves": int(sum(1 for left, right in zip(tree.children_left, tree.children_right) if left == right)),
        "top_split_features": Counter(split_features).most_common(8),
    }


def main():
    parser = argparse.ArgumentParser(description="Export every tree in the simulator Random Forest.")
    parser.add_argument("--seed", type=int, default=20260618)
    parser.add_argument("--elo-file", default=str(DEFAULT_ELO_FILE))
    parser.add_argument("--historical-matches", default=None)
    parser.add_argument("--output-prefix", default="random_forest_trees")
    args = parser.parse_args()

    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, elo_source = build_team_profiles(args.elo_file)
    model_bundle, status = build_match_model_bundle(
        structure,
        profiles,
        args.seed,
        mode="random-forest",
        historical_matches_file=args.historical_matches,
    )
    model = model_bundle["model"]
    feature_names = model_bundle["feature_names"]
    class_names = [str(name) for name in model.classes_]

    prefix = ROOT / args.output_prefix
    text_path = prefix.with_suffix(".txt")
    json_path = prefix.with_suffix(".json")
    summary_path = prefix.with_name(prefix.name + "_summary.json")

    text_lines = [
        "FIFA WC26 Random Forest Tree Export",
        f"seed: {args.seed}",
        f"elo_source: {elo_source}",
        f"model_status: {json.dumps(status, ensure_ascii=False)}",
        f"classes: {', '.join(class_names)}",
        f"features: {', '.join(feature_names)}",
        "",
    ]
    forest_json = {
        "metadata": {
            "seed": args.seed,
            "elo_source": elo_source,
            "model_status": status,
            "classes": class_names,
            "features": feature_names,
        },
        "trees": [],
    }
    summaries = []

    for index, estimator in enumerate(model.estimators_, start=1):
        summary = tree_summary(estimator, feature_names)
        summaries.append({"tree": index, **summary})
        text_lines.append(f"Tree {index:03d}")
        text_lines.append(
            f"nodes={summary['nodes']} max_depth={summary['max_depth']} leaves={summary['leaves']} "
            f"top_features={summary['top_split_features']}"
        )
        text_lines.append(export_text(estimator, feature_names=feature_names, decimals=4))
        text_lines.append("")
        forest_json["trees"].append(
            {
                "tree": index,
                "summary": summary,
                "root": tree_to_dict(estimator, feature_names, class_names),
            }
        )

    text_path.write_text("\n".join(text_lines), encoding="utf-8")
    json_path.write_text(json.dumps(forest_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps({"metadata": forest_json["metadata"], "trees": summaries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {text_path.name}")
    print(f"wrote {json_path.name}")
    print(f"wrote {summary_path.name}")
    print(f"trees: {len(model.estimators_)}")


if __name__ == "__main__":
    main()

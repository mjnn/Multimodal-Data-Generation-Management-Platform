# DEPRECATED — use job2_labeling + job2_embedding + job3_labeling_by_other_model + job4_label_merge_and_compare
# See dataworks/WORKFLOW.md

def main() -> None:
    raise SystemExit(
        "job2_clip_omni is deprecated; use job2_labeling, job2_embedding, "
        "job3_labeling_by_other_model, job4_label_merge_and_compare"
    )


if __name__ == "__main__":
    main()

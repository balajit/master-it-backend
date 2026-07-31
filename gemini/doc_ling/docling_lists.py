for item in doc.texts:
    if item.label == DocItemLabel.LIST_ITEM:
        # Check if the parent is also a LIST_ITEM (indicating a sub-bullet)
        parent_ref = item.parent.cref if item.parent else None

        if parent_ref and "texts" in parent_ref:
            # Simple check if parent is another text item
            print(f"  [Nested Sub-item] {item.text}")
        else:
            print(f"[Top-level Item] {item.text}")
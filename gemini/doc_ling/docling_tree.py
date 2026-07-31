def print_tree(item, item_map, indent_level=0):
    indent = "  " * indent_level
    label_str = getattr(item, "label", "ITEM")
    text_snippet = getattr(item, "text", "")[:50].replace("\n", " ")

    print(f"{indent}• [{label_str}] {text_snippet}")

    # Recurse through all child pointers
    if hasattr(item, "children"):
        for child_ref in item.children:
            child_item = item_map.get(child_ref.cref)
            if child_item:
                print_tree(child_item, item_map, indent_level + 1)


# Build a global map of all JSON pointers across texts, tables, and pictures
full_map = {}
for text_item in doc.texts:
    full_map[f"#/{text_item.self_ref}"] = text_item
for table_item in doc.tables:
    full_map[f"#/{table_item.self_ref}"] = table_item

# Traverse starting from top-level elements (elements with no parent or body parent)
for item in doc.texts:
    if not item.parent or item.parent.cref == "#/body":
        print_tree(item, full_map)
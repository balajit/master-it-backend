def get_parent_heading(item, doc):
    """Recursively traverses parent nodes until it finds a heading."""
    current = item
    while current and hasattr(current, "parent") and current.parent:
        # Resolve parent reference
        parent_item = doc.get_item(current.parent.cref) if hasattr(doc, "get_item") else None

        # Fallback dictionary lookup if doc.get_item is not available
        if not parent_item:
            parent_ref = current.parent.cref.lstrip("#/")
            parent_item = getattr(doc, parent_ref, None)

        if parent_item and parent_item.label in [DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE]:
            return parent_item.text

        current = parent_item
    return "Root / Unknown Section"


# Example: Finding which heading owns each table in the document
for table in doc.tables:
    heading = get_parent_heading(table, doc)
    print(f"Table found under Section: '{heading}'")
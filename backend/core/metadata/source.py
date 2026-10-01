import ast


def literal_eval_node(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def extract_metadata_from_module_ast(tree, metadata_keys) -> dict:
    keys = set(metadata_keys or ())
    for node in getattr(tree, 'body', ()):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in keys:
                    value = literal_eval_node(node.value)
                    if isinstance(value, dict):
                        return value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id in keys:
                value = literal_eval_node(node.value)
                if isinstance(value, dict):
                    return value
    return {}


def extract_metadata_from_class_ast(tree, metadata_keys) -> dict:
    keys = set(metadata_keys or ())
    for node in getattr(tree, 'body', ()):
        if not isinstance(node, ast.ClassDef):
            continue
        for class_node in node.body:
            if isinstance(class_node, ast.Assign):
                for target in class_node.targets:
                    if isinstance(target, ast.Name) and target.id in keys:
                        value = literal_eval_node(class_node.value)
                        if isinstance(value, dict):
                            return value
            elif isinstance(class_node, ast.AnnAssign):
                target = class_node.target
                if isinstance(target, ast.Name) and target.id in keys:
                    value = literal_eval_node(class_node.value)
                    if isinstance(value, dict):
                        return value
    return {}

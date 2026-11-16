export function el(tag, attrs, text) {
  const node = document.createElement(tag);
  if (attrs) {
    const keys = Object.keys(attrs);
    for (let i = 0; i < keys.length; i += 1) {
      const key = keys[i];
      const value = attrs[key];
      if (key === "hidden") node.hidden = !!value;
      else if (value != null) node.setAttribute(key, String(value));
    }
  }
  if (text != null) node.textContent = text;
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

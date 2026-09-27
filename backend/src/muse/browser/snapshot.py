"""Accessibility-style snapshot of the current page.

This is the only place page JavaScript runs, and it is trusted code: it tags visible interactive
elements with per-snapshot ids and reads their role, accessible name and (non-password) value,
plus a text excerpt. Nothing here is reachable from a model-controlled argument.
"""

from typing import Any

from playwright.async_api import Page

MAX_ELEMENTS = 200
MAX_TEXT_CHARS = 6000
ID_ATTRIBUTE = "data-muse-id"

_SCRIPT = """
([attr, maxElements, maxText]) => {
  const selector = [
    'a[href]', 'button', 'input:not([type=hidden])', 'textarea', 'select', 'summary',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=radio]', '[role=tab]',
    '[role=menuitem]', '[role=switch]', '[role=option]', '[contenteditable=""]',
    '[contenteditable=true]'
  ].join(',');
  document.querySelectorAll('[' + attr + ']').forEach(e => e.removeAttribute(attr));
  const implicit = {
    a: 'link', button: 'button', select: 'combobox', textarea: 'textbox', summary: 'button'
  };
  const inputRoles = {
    checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button', reset: 'button'
  };
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
  const elements = [];
  let n = 0;
  for (const el of document.querySelectorAll(selector)) {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const hidden = style.visibility === 'hidden' || style.display === 'none';
    if (box.width === 0 || box.height === 0 || hidden) continue;
    const id = 'e' + (++n);
    el.setAttribute(attr, id);
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || implicit[tag] ||
      (tag === 'input' ? (inputRoles[el.type] || 'textbox') : tag);
    const labelledBy = el.getAttribute('aria-labelledby');
    const name = clean(
      el.getAttribute('aria-label') ||
      (labelledBy && document.getElementById(labelledBy)?.innerText) ||
      (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.innerText || el.getAttribute('placeholder') || el.getAttribute('title') ||
      el.getAttribute('alt') || (el.type !== 'password' ? el.value : '')
    );
    const hasValue = ['input', 'textarea', 'select'].includes(tag) && el.type !== 'password';
    elements.push({id, role, name, value: hasValue ? clean(String(el.value || '')) : null});
    if (n >= maxElements) break;
  }
  const text = (document.body ? document.body.innerText : '')
    .replace(/[ \\t]+/g, ' ').replace(/\\n\\s*\\n+/g, '\\n').trim().slice(0, maxText);
  return {elements, text};
}
"""


async def take_snapshot(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = await page.evaluate(
        _SCRIPT, [ID_ATTRIBUTE, MAX_ELEMENTS, MAX_TEXT_CHARS]
    )
    return result


def element_selector(element_id: str) -> str:
    return f'[{ID_ATTRIBUTE}="{element_id}"]'

/**
 * Svelte action: focus the element when it's mounted.
 *
 * Use instead of the `autofocus` attribute when an element is shown in
 * response to an explicit user action (e.g. entering edit mode) — this
 * avoids the a11y_autofocus warning while preserving the desired UX.
 */
export function focusOnMount(node: HTMLElement) {
	node.focus();
}

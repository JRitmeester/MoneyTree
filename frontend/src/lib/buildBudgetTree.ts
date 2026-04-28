const PATH_SEPARATOR = ' > ';

export interface BudgetTreeNode {
	readonly name: string;
	readonly path: string;
	readonly categoryId: number | null;
	readonly total: number;
	readonly children: readonly BudgetTreeNode[];
}

interface EditLine {
	category_id: number;
	category_name: string;
	amount: number;
}

interface BuildNode {
	name: string;
	path: string;
	categoryId: number | null;
	children: Map<string, BuildNode>;
}

export function buildBudgetTree(
	sectionLines: readonly EditLine[],
	allEditLines: readonly EditLine[],
): BudgetTreeNode[] {
	const roots = new Map<string, BuildNode>();

	for (const line of sectionLines) {
		const segments = line.category_name.split(PATH_SEPARATOR);
		let currentMap = roots;
		let pathSoFar = '';

		for (let i = 0; i < segments.length; i++) {
			const seg = segments[i];
			pathSoFar = pathSoFar ? `${pathSoFar}${PATH_SEPARATOR}${seg}` : seg;
			const isLeaf = i === segments.length - 1;

			if (!currentMap.has(seg)) {
				currentMap.set(seg, {
					name: seg,
					path: pathSoFar,
					categoryId: isLeaf ? line.category_id : null,
					children: new Map(),
				});
			} else if (isLeaf) {
				currentMap.get(seg)!.categoryId = line.category_id;
			}

			currentMap = currentMap.get(seg)!.children;
		}
	}

	function toTreeNodes(map: Map<string, BuildNode>): BudgetTreeNode[] {
		return Array.from(map.values())
			.sort((a, b) => a.name.localeCompare(b.name))
			.map((node) => {
				const children = toTreeNodes(node.children);
				const childTotal = children.reduce((sum, c) => sum + c.total, 0);
				const ownAmount =
					node.categoryId !== null
						? (allEditLines.find((l) => l.category_id === node.categoryId)?.amount ?? 0)
						: 0;

				return {
					name: node.name,
					path: node.path,
					categoryId: node.categoryId,
					total: ownAmount + childTotal,
					children,
				};
			});
	}

	return toTreeNodes(roots);
}

// --- BVA (Actuals) tree ---

export interface BvaTreeNode {
	readonly name: string;
	readonly path: string;
	readonly categoryId: number | null;
	readonly budgeted: number;
	readonly actual: number;
	readonly balance: number;
	readonly children: readonly BvaTreeNode[];
}

interface BvaLine {
	category_id: number;
	category_name: string;
	budgeted: number;
	actual: number;
	balance: number;
}

export function buildBvaTree(lines: readonly BvaLine[]): BvaTreeNode[] {
	const roots = new Map<string, BuildNode>();

	for (const line of lines) {
		const segments = line.category_name.split(PATH_SEPARATOR);
		let currentMap = roots;
		let pathSoFar = '';

		for (let i = 0; i < segments.length; i++) {
			const seg = segments[i];
			pathSoFar = pathSoFar ? `${pathSoFar}${PATH_SEPARATOR}${seg}` : seg;
			const isLeaf = i === segments.length - 1;

			if (!currentMap.has(seg)) {
				currentMap.set(seg, {
					name: seg,
					path: pathSoFar,
					categoryId: isLeaf ? line.category_id : null,
					children: new Map(),
				});
			} else if (isLeaf) {
				currentMap.get(seg)!.categoryId = line.category_id;
			}

			currentMap = currentMap.get(seg)!.children;
		}
	}

	const lineById = new Map(lines.map((l) => [l.category_id, l]));

	function toTreeNodes(map: Map<string, BuildNode>): BvaTreeNode[] {
		return Array.from(map.values())
			.sort((a, b) => a.name.localeCompare(b.name))
			.map((node) => {
				const children = toTreeNodes(node.children);
				const childBudgeted = children.reduce((s, c) => s + c.budgeted, 0);
				const childActual = children.reduce((s, c) => s + c.actual, 0);
				const own = node.categoryId !== null ? lineById.get(node.categoryId) : undefined;

				return {
					name: node.name,
					path: node.path,
					categoryId: node.categoryId,
					budgeted: (own?.budgeted ?? 0) + childBudgeted,
					actual: (own?.actual ?? 0) + childActual,
					balance: own?.balance ?? 0,
					children,
				};
			});
	}

	return toTreeNodes(roots);
}

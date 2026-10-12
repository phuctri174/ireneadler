/// <reference types="vite/client" />
// Every module in this folder is a board template, found here automatically: a new
// template is one module exporting `template` (plus its entry in config/board.json,
// which is how the model learns it exists). The name is the file's.

import type { Template } from "../kit";

const modules = import.meta.glob<{ template: Template<never> }>(["./*.ts", "!./index.ts", "!./_*.ts"], { eager: true });

export const TEMPLATES: Record<string, Template<never>> = Object.fromEntries(
  Object.entries(modules).map(([path, module]) => [path.replace(/^\.\/(.*)\.ts$/, "$1"), module.template]),
);

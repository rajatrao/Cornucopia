import { ATTRIBUTES, DIETS, UNITS } from "./ops";

export type FieldType = "text" | "textarea" | "number" | "integer" | "datetime" | "select" | "multi" | "ref" | "bool";

export interface Field {
  name: string;
  label: string;
  type: FieldType;
  options?: readonly string[];
  ref?: string; // resource kind for reference selects
  required?: boolean;
  editable?: boolean; // present in the update schema
  help?: string;
}

export interface ResourceKind {
  kind: string;
  label: string;
  fields: Field[];
  columns: string[];
  display: (r: Record<string, unknown>) => string;
  note?: string;
}

const t = (name: string, label: string, extra: Partial<Field> = {}): Field => ({ name, label, type: "text", required: true, editable: true, ...extra });

export const RESOURCE_KINDS: ResourceKind[] = [
  {
    kind: "ingredients",
    label: "Ingredients",
    display: (r) => String(r.name),
    columns: ["name", "category", "base_unit", "density_g_per_ml", "unit_weight_g", "attributes"],
    fields: [
      t("name", "Name"),
      t("category", "Category", { type: "select", options: ["grain", "vegetable", "fruit", "protein", "dairy", "fat", "seasoning", "sauce", "bakery", "other"] }),
      t("base_unit", "Base unit", { type: "select", options: ["g", "ml", "each"], editable: false, help: "All stock math uses this unit. Cannot change later." }),
      t("density_g_per_ml", "Density (g/ml)", { type: "number", required: false, help: "Needed to convert volume ↔ mass." }),
      t("unit_weight_g", "Unit weight (g each)", { type: "number", required: false, help: "Needed to convert count ↔ mass." }),
      t("attributes", "Dietary attributes", { type: "multi", options: ATTRIBUTES, required: false }),
      t("perishable_days", "Shelf life (days)", { type: "integer", required: false }),
    ],
  },
  {
    kind: "recipes",
    label: "Recipes",
    display: (r) => String(r.name),
    columns: ["name", "yield_portions", "prep_minutes"],
    fields: [
      t("name", "Name"),
      t("yield_portions", "Yield (portions per batch)", { type: "number" }),
      t("prep_minutes", "Prep time per batch (min)", { type: "integer" }),
      t("instructions", "Instructions", { type: "textarea", required: false }),
    ],
  },
  {
    kind: "recipe-ingredients",
    label: "Recipe ingredients",
    display: (r) => `${r.quantity} ${r.unit}`,
    columns: ["recipe_id", "ingredient_id", "quantity", "unit", "quantity_base", "optional"],
    note: "Quantities per batch. The server converts them to the ingredient's base unit and refuses unsafe conversions.",
    fields: [
      t("recipe_id", "Recipe", { type: "ref", ref: "recipes", editable: false }),
      t("ingredient_id", "Ingredient", { type: "ref", ref: "ingredients", editable: false }),
      t("quantity", "Quantity", { type: "number" }),
      t("unit", "Unit", { type: "select", options: UNITS }),
      t("optional", "Optional", { type: "bool", required: false }),
    ],
  },
  {
    kind: "substitutions",
    label: "Substitution rules",
    display: (r) => `×${r.ratio}`,
    columns: ["ingredient_id", "substitute_id", "ratio", "recipe_id", "notes"],
    note: "Ratio = substitute base units needed per 1 base unit of the original. Leave recipe empty to allow it everywhere.",
    fields: [
      t("ingredient_id", "Original ingredient", { type: "ref", ref: "ingredients", editable: false }),
      t("substitute_id", "Substitute", { type: "ref", ref: "ingredients", editable: false }),
      t("ratio", "Ratio", { type: "number" }),
      t("recipe_id", "Only in recipe", { type: "ref", ref: "recipes", required: false, editable: false }),
      t("notes", "Notes", { required: false }),
    ],
  },
  {
    kind: "meals",
    label: "Meals",
    display: (r) => String(r.name),
    columns: ["name", "description"],
    fields: [t("name", "Name"), t("description", "Description", { required: false })],
  },
  {
    kind: "meal-components",
    label: "Meal components",
    display: (r) => `${r.portions} portion(s)`,
    columns: ["meal_id", "recipe_id", "portions"],
    fields: [
      t("meal_id", "Meal", { type: "ref", ref: "meals", editable: false }),
      t("recipe_id", "Recipe", { type: "ref", ref: "recipes", editable: false }),
      t("portions", "Portions per meal", { type: "number" }),
    ],
  },
  {
    kind: "teams",
    label: "Preparation teams",
    display: (r) => String(r.name),
    columns: ["name", "capacity_portions_per_hour", "available_hours", "active"],
    note: "Capacity and hours change through a Preparation capacity event so the agent sees them.",
    fields: [
      t("name", "Name"),
      t("capacity_portions_per_hour", "Capacity (portions/hour)", { type: "number", editable: false }),
      t("available_hours", "Available hours", { type: "number", editable: false }),
    ],
  },
  {
    kind: "volunteers",
    label: "Volunteers",
    display: (r) => String(r.name),
    columns: ["name", "role", "team_id", "available", "available_hours", "unavailable_reason"],
    note: "Report unavailability from the Event Center.",
    fields: [
      t("name", "Name"),
      t("role", "Role", { type: "select", options: ["cook", "driver", "packer", "coordinator"] }),
      t("team_id", "Team", { type: "ref", ref: "teams", required: false }),
      t("available_hours", "Available hours", { type: "number", required: false }),
    ],
  },
  {
    kind: "deliveries",
    label: "Delivery routes",
    display: (r) => String(r.route_name),
    columns: ["route_name", "capacity_meals", "departs_at", "status", "delay_minutes"],
    note: "Delays and cancellations are reported from the Event Center.",
    fields: [
      t("route_name", "Route"),
      t("capacity_meals", "Capacity (meals)", { type: "integer" }),
      t("departs_at", "Departs at", { type: "datetime", editable: false }),
    ],
  },
  {
    kind: "commitments",
    label: "Commitments",
    display: (r) => `${r.recipient}`,
    columns: ["recipient", "meal_id", "meals_count", "diet_requirements", "due_at", "delivery_id", "status", "version"],
    note: "Meal count, diet, due time and status change through a Commitment changed event.",
    fields: [
      t("recipient", "Recipient"),
      t("meal_id", "Meal", { type: "ref", ref: "meals", editable: false }),
      t("meals_count", "Meals", { type: "integer", editable: false }),
      t("diet_requirements", "Dietary requirements", { type: "multi", options: DIETS, required: false, editable: false }),
      t("due_at", "Due at", { type: "datetime", editable: false }),
      t("delivery_id", "Delivery route", { type: "ref", ref: "deliveries", required: false }),
    ],
  },
  {
    kind: "donors",
    label: "Donors",
    display: (r) => String(r.name),
    columns: ["name", "kind", "contact"],
    fields: [
      t("name", "Name"),
      t("kind", "Kind", { type: "select", options: ["individual", "business", "farm", "organization"] }),
      t("contact", "Contact", { required: false }),
    ],
  },
];

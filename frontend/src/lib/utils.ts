import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export const cn = (...v: ClassValue[]) => twMerge(clsx(v));

export const PARAM_RU: Record<string, string> = {
  medium_temperature: "Температура среды", ambient_temperature: "Температура окр. воздуха",
  bearing_temperature: "Температура подшипн. узла", working_pressure: "Рабочее давление",
  test_pressure: "Испытательное давление", flow_rate: "Подача", head: "Напор", rotation_speed: "Частота вращения",
  power: "Мощность", vibration_velocity: "Виброскорость", noise_level: "Уровень звука", service_life: "Ресурс",
  mass: "Масса", ingress_protection: "Степень защиты", voltage: "Напряжение", torque: "Крутящий момент",
  material_temperature: "Температура применения",
};
export const KIND_RU: Record<string, string> = { demand: "требование", capability: "возможность", setpoint: "уставка", nominal: "номинал" };
export const TYPE_RU: Record<string, string> = {
  Product: "Изделие", Assembly: "Сборочная единица", Component: "Деталь", Material: "Материал",
  TechnicalRequirement: "Требование", EngineeringDocument: "Документ", Test: "Испытание", Standard: "НТД",
  ChangeRequest: "Извещение", Constraint: "Характеристика",
};
export const DOCTYPE_RU: Record<string, string> = {
  TechnicalSpecification: "Техническое задание", Specification: "Спецификация", ExplanatoryNote: "Пояснительная записка",
  MaterialRequirements: "Ведомость материалов", ComponentSpecification: "ТУ / ТТ", Calculation: "Расчёт",
  TestProgram: "ПМИ", TestReport: "Протокол испытаний", OperationManual: "Руководство по эксплуатации",
  Passport: "Паспорт", Setpoints: "Карта уставок", ChangeLog: "Журнал изменений",
};

export function fmtReq(r: { operator: string; value: number | string | null; low: number | null; high: number | null; unit: string }) {
  const u = r.unit ? ` ${r.unit}` : "";
  const n = (x: number | string | null) => (typeof x === "number" ? String(+x.toFixed(4)).replace(".", ",") : String(x ?? ""));
  if (r.operator === "range") return `${n(r.low)} … ${n(r.high)}${u}`;
  const op = r.operator === "<=" ? "≤ " : r.operator === ">=" ? "≥ " : "";
  return `${op}${n(r.value)}${u}`;
}

export function store(key: string, value?: string | null): string | null {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* хранилище недоступно */ }
  return null;
}

export interface Session { access_token: string; expires_in: number }
export interface CurrentUser { usuario_id: number; activo: boolean | null; es_administrador: boolean | null }
export interface User {
  usuario_id: number; nombre: string | null; apellido1: string | null; apellido2: string | null;
  activo: boolean | null; es_administrador: boolean | null; nombre_usuario: string | null;
}
export interface Project {
  proyecto_id: number; nombre: string | null; descripcion: string | null;
  duracion: number | null; restantes: number | null; color: string | null; laborable: boolean;
}
export interface DateType {
  tipo_id: number; nombre: string | null; descripcion: string | null;
  color: string | null; en_borde: boolean | null;
}
export interface Assignment {
  fecha: string; proyecto_id: number; nombre: string | null; color: string | null; laborable: boolean; es_prevision: boolean;
}
export interface Typing {
  fecha: string; tipo_id: number; nombre: string | null; color: string | null; en_borde: boolean | null;
}
export interface VacationColor { color: string | null; es_prevision: boolean }
export interface VacationContext { anterior: VacationColor[]; posterior: VacationColor[] }
export interface Note { fecha: string; texto: string }
export interface CalendarData { asignaciones: Assignment[]; tipados: Typing[]; notas: Note[]; contexto_vacaciones: VacationContext }
export interface Day { number: number; date: string; assignments: Assignment[]; typings: Typing[]; note: string | null }
export interface Month { name: string; days: (Day | null)[] }
export type View = 'calendar' | 'usuarios' | 'proyectos' | 'tipos';
export type EditableUser = Omit<User, 'usuario_id'> & { password: string };
export type EditableProject = Omit<Project, 'proyecto_id'>;
export type EditableType = Omit<DateType, 'tipo_id'>;

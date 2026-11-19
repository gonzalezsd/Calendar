import { Component, OnInit } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

interface Session { access_token: string; expires_in: number }
interface CurrentUser { usuario_id: number; activo: boolean | null; es_administrador: boolean | null }
interface User {
  usuario_id: number; nombre: string | null; apellido1: string | null; apellido2: string | null;
  activo: boolean | null; es_administrador: boolean | null; nombre_usuario: string | null;
}
interface Project {
  proyecto_id: number; nombre: string | null; descripcion: string | null;
  duracion: number | null; restantes: number | null; color: string | null;
}
interface DateType {
  tipo_id: number; nombre: string | null; descripcion: string | null;
  color: string | null; en_borde: boolean | null;
}
interface Assignment {
  fecha: string; proyecto_id: number; nombre: string | null; color: string | null; es_prevision: boolean;
}
interface Typing {
  fecha: string; tipo_id: number; nombre: string | null; color: string | null; en_borde: boolean | null;
}
interface CalendarData { asignaciones: Assignment[]; tipados: Typing[] }
interface Day { number: number; date: string; assignments: Assignment[]; typings: Typing[] }
interface Month { name: string; days: (Day | null)[] }
type View = 'calendar' | 'usuarios' | 'proyectos' | 'tipos';
type EditableUser = Omit<User, 'usuario_id'> & { password: string };
type EditableProject = Omit<Project, 'proyecto_id'>;
type EditableType = Omit<DateType, 'tipo_id'>;

@Component({
  selector: 'app-root',
  imports: [FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App implements OnInit {
  private readonly tokenKey = 'calendar_token';
  private readonly expiryKey = 'calendar_expiry';
  private token = '';
  private calendarRequest = 0;
  private expiryTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly months = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
  readonly weekdays = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];

  user: CurrentUser | null = null;
  loginName = '';
  loginPassword = '';
  loading = false;
  calendarLoading = false;
  error = '';
  message = '';
  view: View = 'calendar';
  menuOpen = false;
  years: number[] = [];
  year: number | null = null;
  newYear = new Date().getFullYear();
  calendar: Month[] = [];
  users: User[] = [];
  projects: Project[] = [];
  dateTypes: DateType[] = [];
  editingId: number | null = null;
  userForm: EditableUser = this.emptyUser();
  projectForm: EditableProject = this.emptyProject();
  typeForm: EditableType = this.emptyType();

  constructor(private readonly http: HttpClient) {}

  async ngOnInit(): Promise<void> {
    const savedToken = localStorage.getItem(this.tokenKey);
    const expiry = Number(localStorage.getItem(this.expiryKey));
    if (savedToken && expiry > Date.now()) {
      this.token = savedToken;
      this.scheduleExpiry(expiry);
      await this.run(async () => this.loadSession());
    } else {
      this.clearSession();
    }
  }

  async login(form: NgForm): Promise<void> {
    if (form.invalid) return;
    await this.run(async () => {
      const session = await firstValueFrom(this.http.post<Session>('/api/auth/login', {
        nombre_usuario: this.loginName, password: this.loginPassword
      }));
      this.loginPassword = '';
      this.token = session.access_token;
      localStorage.setItem(this.tokenKey, this.token);
      const expiry = Date.now() + session.expires_in * 1000;
      localStorage.setItem(this.expiryKey, String(expiry));
      this.scheduleExpiry(expiry);
      await this.loadSession();
    });
  }

  logout(): void {
    this.clearSession();
    this.error = '';
    this.message = '';
  }

  private clearSession(): void {
    this.calendarRequest++;
    if (this.expiryTimer !== null) clearTimeout(this.expiryTimer);
    this.expiryTimer = null;
    this.token = '';
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.expiryKey);
    this.user = null;
    this.loginName = '';
    this.loginPassword = '';
    this.years = [];
    this.year = null;
    this.calendar = [];
    this.calendarLoading = false;
    this.users = [];
    this.projects = [];
    this.dateTypes = [];
    this.view = 'calendar';
    this.menuOpen = false;
    this.resetForm();
  }

  private scheduleExpiry(expiry: number): void {
    if (this.expiryTimer !== null) clearTimeout(this.expiryTimer);
    this.expiryTimer = setTimeout(() => {
      this.clearSession();
      this.error = 'La sesión ha caducado. Inicia sesión de nuevo.';
    }, Math.max(0, expiry - Date.now()));
  }

  private async loadSession(): Promise<void> {
    this.user = await this.request<CurrentUser>('GET', '/api/me');
    await this.loadYears();
  }

  private async request<T>(method: string, url: string, body?: unknown): Promise<T> {
    const headers = new HttpHeaders({ Authorization: `Bearer ${this.token}` });
    return firstValueFrom(this.http.request<T>(method, url, { body, headers }));
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.error = '';
    this.message = '';
    this.loading = true;
    try {
      await action();
    } catch (error) {
      this.showError(error);
    } finally {
      this.loading = false;
    }
  }

  private showError(error: unknown): void {
    if (error instanceof HttpErrorResponse && error.status === 401 && this.token) {
      this.clearSession();
      this.error = 'La sesión ha caducado o ya no es válida. Inicia sesión de nuevo.';
    } else if (error instanceof HttpErrorResponse && typeof error.error?.error === 'string') {
      this.error = error.error.error;
    } else {
      this.error = 'No se ha podido completar la operación. Comprueba la conexión e inténtalo de nuevo.';
    }
  }

  async loadYears(preferred?: number): Promise<void> {
    const result = await this.request<{ years: number[] }>('GET', '/api/get_years');
    this.years = result.years;
    const selected = preferred ?? this.year ?? new Date().getFullYear();
    this.year = this.years.includes(selected) ? selected : (this.years.at(-1) ?? null);
    if (this.year !== null) await this.loadCalendar(this.year);
    else this.calendar = [];
  }

  async changeYear(value: string): Promise<void> {
    const selected = Number(value);
    if (!this.years.includes(selected)) return;
    this.year = selected;
    this.view = 'calendar';
    this.error = '';
    try {
      await this.loadCalendar(selected);
    } catch (error) {
      this.showError(error);
    }
  }

  private async loadCalendar(year: number): Promise<void> {
    const sequence = ++this.calendarRequest;
    this.calendar = [];
    this.calendarLoading = true;
    try {
      const data = await this.request<CalendarData>('GET', `/api/calendario/${year}`);
      if (sequence === this.calendarRequest) this.calendar = this.buildCalendar(year, data);
    } catch (error) {
      if (sequence === this.calendarRequest) throw error;
    } finally {
      if (sequence === this.calendarRequest) this.calendarLoading = false;
    }
  }

  private buildCalendar(year: number, data: CalendarData): Month[] {
    return this.months.map((name, month) => {
      const first = new Date(0);
      first.setFullYear(year, month, 1);
      first.setHours(0, 0, 0, 0);
      const last = new Date(0);
      last.setFullYear(year, month + 1, 0);
      const days: (Day | null)[] = Array((first.getDay() + 6) % 7).fill(null);
      for (let day = 1; day <= last.getDate(); day++) {
        const key = `${String(year).padStart(4, '0')}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        days.push({
          number: day, date: key,
          assignments: data.asignaciones.filter(item => item.fecha === key),
          typings: data.tipados.filter(item => item.fecha === key)
        });
      }
      return { name, days };
    });
  }

  async createYear(form: NgForm): Promise<void> {
    if (form.invalid || !Number.isInteger(this.newYear)) return;
    await this.run(async () => {
      await this.request('POST', '/api/new_year', { year: this.newYear });
      await this.loadYears(this.newYear);
      this.view = 'calendar';
      this.message = 'Año creado.';
    });
  }

  async navigate(view: View): Promise<void> {
    this.menuOpen = false;
    this.view = view;
    this.resetForm();
    if (view === 'calendar') return;
    await this.run(async () => {
      if (view === 'usuarios') this.users = await this.request<User[]>('GET', '/api/usuarios');
      if (view === 'proyectos') this.projects = await this.request<Project[]>('GET', '/api/proyectos');
      if (view === 'tipos') this.dateTypes = await this.request<DateType[]>('GET', '/api/tipos-fecha');
    });
  }

  editUser(user: User): void {
    this.editingId = user.usuario_id;
    this.userForm = { ...user, password: '' };
  }
  editProject(project: Project): void {
    this.editingId = project.proyecto_id;
    this.projectForm = { ...project };
  }
  editType(type: DateType): void {
    this.editingId = type.tipo_id;
    this.typeForm = { ...type };
  }
  resetForm(): void {
    this.editingId = null;
    this.userForm = this.emptyUser();
    this.projectForm = this.emptyProject();
    this.typeForm = this.emptyType();
  }
  private emptyUser(): EditableUser {
    return { nombre: '', apellido1: '', apellido2: '', nombre_usuario: '', password: '', activo: true, es_administrador: false };
  }
  private emptyProject(): EditableProject {
    return { nombre: '', descripcion: '', duracion: null, restantes: null, color: '#4f46e5' };
  }
  private emptyType(): EditableType {
    return { nombre: '', descripcion: '', color: '#ef4444', en_borde: false };
  }

  async saveUser(form: NgForm): Promise<void> {
    if (form.invalid) return;
    await this.run(async () => {
      const current = this.users.find(user => user.usuario_id === this.editingId);
      const payload: Record<string, unknown> = {};
      for (const field of ['nombre', 'apellido1', 'apellido2', 'activo', 'es_administrador'] as const) {
        if (!current || this.userForm[field] !== current[field]) payload[field] = this.userForm[field];
      }
      if (this.editingId === null || this.userForm.nombre_usuario !== current?.nombre_usuario) {
        payload['nombre_usuario'] = this.userForm.nombre_usuario;
      }
      if (this.userForm.password) payload['password'] = this.userForm.password;
      if (this.editingId !== null && Object.keys(payload).length === 0) {
        this.resetForm();
        this.message = 'No hay cambios que guardar.';
        return;
      }
      const url = this.editingId === null ? '/api/usuarios' : `/api/usuarios/${this.editingId}`;
      await this.request(this.editingId === null ? 'POST' : 'PATCH', url, payload);
      this.resetForm();
      this.user = await this.request<CurrentUser>('GET', '/api/me');
      if (this.user.es_administrador) {
        this.users = await this.request<User[]>('GET', '/api/usuarios');
      } else {
        this.view = 'calendar';
        this.users = [];
      }
      this.message = 'Usuario guardado.';
    });
  }

  async saveProject(form: NgForm): Promise<void> {
    if (form.invalid) return;
    await this.run(async () => {
      const { nombre, descripcion, duracion, restantes, color } = this.projectForm;
      const url = this.editingId === null ? '/api/proyectos' : `/api/proyectos/${this.editingId}`;
      await this.request(this.editingId === null ? 'POST' : 'PATCH', url, { nombre, descripcion, duracion, restantes, color });
      this.resetForm();
      this.projects = await this.request<Project[]>('GET', '/api/proyectos');
      if (this.year !== null) await this.loadCalendar(this.year);
      this.message = 'Proyecto guardado.';
    });
  }

  async saveType(form: NgForm): Promise<void> {
    if (form.invalid) return;
    await this.run(async () => {
      const { nombre, descripcion, color, en_borde } = this.typeForm;
      const current = this.dateTypes.find(type => type.tipo_id === this.editingId);
      const payload: Record<string, unknown> = { nombre, descripcion, color };
      if (!current || en_borde !== current.en_borde) payload['en_borde'] = en_borde;
      const url = this.editingId === null ? '/api/tipos-fecha' : `/api/tipos-fecha/${this.editingId}`;
      await this.request(this.editingId === null ? 'POST' : 'PATCH', url, payload);
      this.resetForm();
      this.dateTypes = await this.request<DateType[]>('GET', '/api/tipos-fecha');
      if (this.year !== null) await this.loadCalendar(this.year);
      this.message = 'Tipo de fecha guardado.';
    });
  }
}

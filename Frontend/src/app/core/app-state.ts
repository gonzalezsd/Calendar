import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { CalendarData, CurrentUser, Day, Month, Reminder, Session, VacationContext, View } from './models';

@Injectable({ providedIn: 'root' })
export class AppState {
  private readonly tokenKey = 'calendar_token';
  private readonly expiryKey = 'calendar_expiry';
  private token = '';
  private calendarRequest = 0;
  private expiryTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly months = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

  user: CurrentUser | null = null;
  loading = false;
  calendarLoading = false;
  error = '';
  message = '';
  view: View = 'calendar';
  editTarget: { view: 'proyectos' | 'tipos'; id: number } | null = null;
  menuOpen = false;
  years: number[] = [];
  year: number | null = null;
  calendar: Month[] = [];
  loginReminders: Reminder[] = [];
  vacationContext: VacationContext = { anterior: [], posterior: [] };

  constructor(private readonly http: HttpClient) {}

  async restore(): Promise<void> {
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

  async login(username: string, password: string): Promise<boolean> {
    let authenticated = false;
    await this.run(async () => {
      const session = await firstValueFrom(this.http.post<Session>('/api/auth/login', {
        nombre_usuario: username, password
      }));
      this.token = session.access_token;
      localStorage.setItem(this.tokenKey, this.token);
      const expiry = Date.now() + session.expires_in * 1000;
      localStorage.setItem(this.expiryKey, String(expiry));
      this.scheduleExpiry(expiry);
      authenticated = true;
      await this.loadSession();
      const today = new Date();
      const day = `${String(today.getFullYear()).padStart(4, '0')}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
      const reminders = await this.request<Reminder[]>('GET', `/api/recordatorios/${day}`);
      if (this.token === session.access_token) this.loginReminders = reminders;
    });
    return authenticated;
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
    this.years = [];
    this.year = null;
    this.calendar = [];
    this.loginReminders = [];
    this.vacationContext = { anterior: [], posterior: [] };
    this.calendarLoading = false;
    this.view = 'calendar';
    this.editTarget = null;
    this.menuOpen = false;
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

  async request<T>(method: string, url: string, body?: unknown): Promise<T> {
    const headers = new HttpHeaders({ Authorization: `Bearer ${this.token}` });
    return firstValueFrom(this.http.request<T>(method, url, { body, headers }));
  }

  async requestCsv(url: string): Promise<string> {
    const headers = new HttpHeaders({ Authorization: `Bearer ${this.token}` });
    try {
      return await firstValueFrom(this.http.get(url, { headers, responseType: 'text' }));
    } catch (error) {
      if (error instanceof HttpErrorResponse && typeof error.error === 'string') {
        let body: unknown;
        try {
          body = JSON.parse(error.error);
        } catch (parseError) {
          if (!(parseError instanceof SyntaxError)) throw parseError;
          throw error;
        }
        throw new HttpErrorResponse({
          error: body, headers: error.headers, status: error.status, statusText: error.statusText,
          url: error.url ?? undefined
        });
      }
      throw error;
    }
  }

  async run(action: () => Promise<void>): Promise<void> {
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

  showError(error: unknown): void {
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

  async loadCalendar(year: number): Promise<void> {
    const sequence = ++this.calendarRequest;
    this.calendar = [];
    this.vacationContext = { anterior: [], posterior: [] };
    this.calendarLoading = true;
    try {
      const data = await this.request<CalendarData>('GET', `/api/calendario/${year}`);
      if (sequence === this.calendarRequest) {
        this.calendar = this.buildCalendar(year, data);
        this.vacationContext = data.contexto_vacaciones;
      }
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
          typings: data.tipados.filter(item => item.fecha === key),
          note: data.notas.find(item => item.fecha === key)?.texto ?? null,
          reminders: data.recordatorios.filter(item => item.fecha === key)
        });
      }
      return { name, days };
    });
  }
}

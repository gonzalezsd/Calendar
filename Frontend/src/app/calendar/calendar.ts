import { Component, DoCheck, ElementRef, HostListener, ViewChild } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';
import { Assignment, DateType, Day, Month, Project, Typing, VacationColor } from '../core/models';

@Component({
  selector: 'app-calendar',
  imports: [FormsModule],
  templateUrl: './calendar.html'
})
export class CalendarComponent implements DoCheck {
  readonly weekdays = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
  newYear = new Date().getFullYear();
  selectedMonth: number | null = null;
  annualInfoOpen = false;
  bulkAssignOpen = false;
  selectedDay: Day | null = null;
  noteDraft = '';
  readonly selectedDates = new Set<string>();
  private selectionYear: number | null;
  projects: Project[] = [];
  dateTypes: DateType[] = [];
  catalogsLoaded = false;
  refreshFailed = false;
  selectedProjectId: number | null = null;
  selectedTypeId: number | null = null;
  forecast = false;
  bulkForecast = false;
  readonly bulkProjectIds = new Set<number>();
  readonly bulkTypeIds = new Set<number>();

  constructor(readonly state: AppState) {
    this.selectionYear = state.year;
  }

  @ViewChild('closeDayButton') set closeDayButton(button: ElementRef<HTMLButtonElement> | undefined) {
    button?.nativeElement.focus();
  }

  @ViewChild('closeAnnualButton') set closeAnnualButton(button: ElementRef<HTMLButtonElement> | undefined) {
    button?.nativeElement.focus();
  }

  @ViewChild('closeBulkButton') set closeBulkButton(button: ElementRef<HTMLButtonElement> | undefined) {
    button?.nativeElement.focus();
  }

  ngDoCheck(): void {
    if (this.selectionYear !== this.state.year) {
      this.selectionYear = this.state.year;
      this.selectedDates.clear();
      this.selectedDay = null;
      this.bulkAssignOpen = false;
    }
  }

  showMonth(index: number): void {
    if (this.selectedMonth === index) return;
    if (!this.canLeaveDay()) return;
    this.dismissDay();
    this.annualInfoOpen = false;
    this.bulkAssignOpen = false;
    this.selectedMonth = index;
  }

  showYear(): void {
    if (this.selectedMonth !== null) {
      if (!this.canLeaveDay()) return;
      this.dismissDay();
      this.annualInfoOpen = false;
    }
    this.selectedMonth = null;
  }

  async selectDay(day: Day, event: MouseEvent): Promise<void> {
    if (this.selectedDay === day && !event.shiftKey) return;
    if (!this.canLeaveDay()) return;
    this.annualInfoOpen = false;
    this.bulkAssignOpen = false;
    if (event.shiftKey) {
      this.dismissDay();
      this.selectedDates.add(day.date);
      return;
    }
    this.selectedDates.clear();
    this.selectedDates.add(day.date);
    this.selectedDay = day;
    this.noteDraft = day.note ?? '';
    this.selectedProjectId = null;
    this.selectedTypeId = null;
    this.forecast = false;
    this.refreshFailed = false;
    await this.loadCatalogs();
  }

  async loadCatalogs(): Promise<void> {
    this.catalogsLoaded = false;
    await this.state.run(async () => {
      [this.projects, this.dateTypes] = await Promise.all([
        this.state.request<Project[]>('GET', '/api/proyectos'),
        this.state.request<DateType[]>('GET', '/api/tipos-fecha')
      ]);
      this.catalogsLoaded = true;
    });
  }

  async openAnnualInfo(): Promise<void> {
    if (!this.canLeaveDay()) return;
    this.dismissDay();
    this.bulkAssignOpen = false;
    this.annualInfoOpen = true;
    await this.loadCatalogs();
  }

  async openBulkAssign(): Promise<void> {
    if (!this.canLeaveDay()) return;
    this.dismissDay();
    this.annualInfoOpen = false;
    this.bulkProjectIds.clear();
    this.bulkTypeIds.clear();
    this.bulkForecast = false;
    this.bulkAssignOpen = true;
    await this.loadCatalogs();
  }

  closeBulkAssign(): void {
    this.bulkAssignOpen = false;
    document.getElementById('bulk-assign-button')?.focus();
  }

  toggleBulkSelection(selection: Set<number>, id: number): void {
    if (selection.has(id)) selection.delete(id);
    else selection.add(id);
  }

  async assignSelectedDays(): Promise<void> {
    const year = this.state.year;
    if (year === null || this.selectedDates.size < 2 || (!this.bulkProjectIds.size && !this.bulkTypeIds.size)) return;
    const body = {
      fechas: [...this.selectedDates].sort(),
      proyectos: [...this.bulkProjectIds],
      tipos: [...this.bulkTypeIds],
      es_prevision: this.bulkForecast
    };
    await this.state.run(async () => {
      await this.state.request('POST', '/api/asignaciones/multiples', body);
      this.state.message = 'Asignaciones guardadas.';
      if (this.state.year === year) {
        this.selectedDates.clear();
        this.bulkAssignOpen = false;
        await this.state.loadCalendar(year);
      }
    });
  }

  closeAnnualInfo(): void {
    this.annualInfoOpen = false;
    document.getElementById('annual-info-button')?.focus();
  }

  get todayDate(): string {
    const today = new Date();
    return `${String(today.getFullYear()).padStart(4, '0')}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  }

  workedDaysInMonth(month: Month): number {
    return month.days.filter(day => day && this.isWorkedDay(day)).length;
  }

  private isWorkedDay(day: Day): boolean {
    return day.assignments.some(project => project.laborable && !project.es_prevision);
  }

  get periodSummary() {
    const projectDays = new Map<number, number>();
    const projectWorkedDays = new Map<number, number>();
    const typeDays = new Map<number, number>();
    let workingDays = 0;
    let workedDays = 0;

    for (const [index, month] of this.state.calendar.entries()) {
      if (this.selectedMonth !== null && index !== this.selectedMonth) continue;
      for (const day of month.days) {
        if (!day) continue;
        if (!day.typings.some(type => type.nombre === 'Festivo') &&
            !day.assignments.some(project => project.nombre === 'Vacaciones')) workingDays++;
        if (this.isWorkedDay(day)) workedDays++;
        for (const id of new Set(day.assignments.map(project => project.proyecto_id))) {
          projectDays.set(id, (projectDays.get(id) ?? 0) + 1);
        }
        for (const id of new Set(day.assignments.filter(project => !project.es_prevision).map(project => project.proyecto_id))) {
          projectWorkedDays.set(id, (projectWorkedDays.get(id) ?? 0) + 1);
        }
        for (const id of new Set(day.typings.map(type => type.tipo_id))) {
          typeDays.set(id, (typeDays.get(id) ?? 0) + 1);
        }
      }
    }

    return {
      workingDays,
      workedDays,
      projects: this.projects.map(project => ({
        ...project, days: projectDays.get(project.proyecto_id) ?? 0,
        workedDays: projectWorkedDays.get(project.proyecto_id) ?? 0
      })),
      types: this.dateTypes.map(type => ({ ...type, days: typeDays.get(type.tipo_id) ?? 0 }))
    };
  }

  @HostListener('document:keydown.escape')
  closeDay(): void {
    if (this.bulkAssignOpen) {
      this.closeBulkAssign();
      return;
    }
    if (this.annualInfoOpen) {
      this.closeAnnualInfo();
      return;
    }
    if (!this.canLeaveDay()) return;
    const date = this.dismissDay();
    if (date) document.querySelector<HTMLButtonElement>(`.day[aria-label="${date}"]`)?.focus();
  }

  private dismissDay(): string | undefined {
    const date = this.selectedDay?.date;
    if (date) this.selectedDates.delete(date);
    this.selectedDay = null;
    this.noteDraft = '';
    return date;
  }

  get noteDirty(): boolean {
    return !!this.selectedDay && this.noteDraft !== (this.selectedDay.note ?? '');
  }

  canLeaveDay(): boolean {
    return !this.noteDirty || window.confirm('Hay cambios en la nota sin guardar. ¿Descartarlos?');
  }

  @HostListener('window:beforeunload', ['$event'])
  beforeUnload(event: BeforeUnloadEvent): void {
    if (this.noteDirty) event.preventDefault();
  }

  openItem(view: 'proyectos' | 'tipos', id: number): void {
    if (!this.canLeaveDay()) return;
    this.state.editTarget = { view, id };
    this.state.menuOpen = false;
    this.state.view = view;
  }

  async saveNote(day: Day): Promise<void> {
    const text = this.noteDraft;
    if (!this.noteDirty || (!day.note && !text.trim())) return;
    await this.state.run(async () => {
      if (text.trim()) {
        await this.state.request('PUT', `/api/notas/${day.date}`, { texto: text });
        day.note = text;
      } else {
        await this.state.request('DELETE', `/api/notas/${day.date}`);
        day.note = null;
        this.noteDraft = '';
      }
      this.state.message = 'Nota guardada.';
    });
  }

  canAddProject(day: Day): boolean {
    return this.selectedProjectId !== null && !day.assignments.some(
      item => item.proyecto_id === this.selectedProjectId && item.es_prevision === this.forecast
    );
  }

  canAddType(day: Day): boolean {
    const type = this.dateTypes.find(item => item.tipo_id === this.selectedTypeId);
    return !!type && type.en_borde !== null &&
      !day.typings.some(item => item.en_borde === null || item.en_borde === type.en_borde);
  }

  async addProject(day: Day): Promise<void> {
    const project = this.projects.find(item => item.proyecto_id === this.selectedProjectId);
    if (!project || !this.canAddProject(day)) return;
    const assignment: Assignment = {
      fecha: day.date, proyecto_id: project.proyecto_id, nombre: project.nombre,
      color: project.color, laborable: project.laborable, es_prevision: this.forecast
    };
    await this.updateDay(day, 'POST', '/api/asignaciones', () => day.assignments.push(assignment), {
      fecha: day.date, proyecto_id: project.proyecto_id, es_prevision: this.forecast
    });
  }

  async removeProject(day: Day, assignment: Assignment): Promise<void> {
    await this.updateDay(day, 'DELETE',
      `/api/asignaciones/${day.date}/${assignment.proyecto_id}/${assignment.es_prevision}`,
      () => { day.assignments = day.assignments.filter(item => item !== assignment); });
  }

  async confirmProject(day: Day, assignment: Assignment): Promise<void> {
    await this.updateDay(day, 'POST', `/api/asignaciones/${day.date}/${assignment.proyecto_id}/confirmar`, () => {
      if (day.assignments.some(item => item.proyecto_id === assignment.proyecto_id && !item.es_prevision)) {
        day.assignments = day.assignments.filter(item => item !== assignment);
      } else {
        day.assignments = day.assignments.map(item =>
          item === assignment ? { ...item, es_prevision: false } : item
        );
      }
    });
  }

  async addType(day: Day): Promise<void> {
    const type = this.dateTypes.find(item => item.tipo_id === this.selectedTypeId);
    if (!type || !this.canAddType(day)) return;
    const typing: Typing = {
      fecha: day.date, tipo_id: type.tipo_id, nombre: type.nombre, color: type.color, en_borde: type.en_borde
    };
    await this.updateDay(day, 'POST', '/api/tipados', () => day.typings.push(typing), {
      fecha: day.date, tipo_id: type.tipo_id
    });
  }

  async removeType(day: Day, typing: Typing): Promise<void> {
    await this.updateDay(day, 'DELETE', `/api/tipados/${day.date}/${typing.tipo_id}`,
      () => { day.typings = day.typings.filter(item => item !== typing); });
  }

  private async updateDay(day: Day, method: string, url: string, apply: () => void, body?: object): Promise<void> {
    await this.state.run(async () => {
      await this.state.request(method, url, body);
      apply();
      this.state.message = 'La asignación se ha guardado.';
      await this.refreshCalendar(day);
      this.state.message = 'Asignaciones actualizadas.';
    });
  }

  async retryRefresh(day: Day): Promise<void> {
    await this.state.run(async () => {
      await this.refreshCalendar(day);
      this.state.message = 'Calendario actualizado.';
    });
  }

  async reloadCalendar(): Promise<void> {
    const year = this.state.year;
    if (year === null) return;
    await this.state.run(async () => {
      await this.state.loadCalendar(year);
      this.state.message = 'Calendario actualizado.';
    });
  }

  private async refreshCalendar(day: Day): Promise<void> {
    const year = Number(day.date.slice(0, 4));
    if (this.state.year !== year) return;
    try {
      await this.state.loadCalendar(year);
      this.refreshFailed = false;
      if (this.selectedDay === day && this.state.year === year) {
        this.selectedDay = this.state.calendar.flatMap(month => month.days).find(item => item?.date === day.date) ?? null;
      }
    } catch (error) {
      this.refreshFailed = true;
      throw error;
    }
  }

  getTypingBorderStyle(day: Day): string | null {
    const typing = day.typings.find(item => item.en_borde);
    return typing ? `2px solid ${typing.color || '#9ca3af'}` : null;
  }

  getTypingNumberColor(day: Day): string | null {
    const typing = day.typings.find(item => !item.en_borde);
    return typing ? typing.color || '#9ca3af' : null;
  }

  getProjectBackground(day: Day): string | null {
    const first = day.assignments[0];
    if (!first) return null;
    const color = day.assignments.some(item => item.proyecto_id !== first.proyecto_id)
      ? '#2C813A' : first.color || '#9ca3af';
    return this.assignmentColor(color, day.assignments.every(item => item.es_prevision));
  }

  vacationBackgrounds(): Map<string, string> {
    const days = this.state.calendar.flatMap(month => month.days).filter((day): day is Day => day !== null);
    const result = new Map<string, string>();
    const isNonWorking = (day: Day): boolean => {
      const weekday = new Date(`${day.date}T12:00:00`).getDay();
      return weekday === 0 || weekday === 6 || day.typings.some(type => type.nombre === 'Festivo');
    };
    const vacations = (day: Day): VacationColor[] => day.assignments.filter(item => item.nombre === 'Vacaciones');

    for (let start = 0; start < days.length;) {
      if (!isNonWorking(days[start])) {
        start++;
        continue;
      }
      let end = start + 1;
      while (end < days.length && isNonWorking(days[end])) end++;
      const nearby = [
        ...(start > 0 ? vacations(days[start - 1]) : this.state.vacationContext.anterior),
        ...days.slice(start, end).flatMap(vacations),
        ...(end < days.length ? vacations(days[end]) : this.state.vacationContext.posterior)
      ];
      const vacation = nearby.find(item => !item.es_prevision) ?? nearby[0];
      if (vacation) {
        const color = this.assignmentColor(vacation.color || '#9ca3af', vacation.es_prevision);
        for (const day of days.slice(start, end)) {
          if (!day.assignments.length) result.set(day.date, color);
        }
      }
      start = end;
    }
    return result;
  }

  private assignmentColor(color: string, forecast: boolean): string {
    return forecast ? `color-mix(in srgb, ${color} 50%, white)` : color;
  }

  async createYear(form: NgForm): Promise<void> {
    if (form.invalid || !Number.isInteger(this.newYear)) return;
    if (!this.canLeaveDay()) return;
    await this.state.run(async () => {
      await this.state.request('POST', '/api/new_year', { year: this.newYear });
      await this.state.loadYears(this.newYear);
      this.state.view = 'calendar';
      this.state.message = 'Año creado.';
    });
  }
}

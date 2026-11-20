import { Component, DoCheck, ElementRef, HostListener, ViewChild } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';
import { Assignment, DateType, Day, Project, Typing } from '../core/models';

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
    this.dismissDay();
    this.annualInfoOpen = false;
    this.bulkAssignOpen = false;
    this.selectedMonth = index;
  }

  showYear(): void {
    if (this.selectedMonth !== null) this.dismissDay();
    this.selectedMonth = null;
  }

  async selectDay(day: Day, event: MouseEvent): Promise<void> {
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
    this.dismissDay();
    this.bulkAssignOpen = false;
    this.annualInfoOpen = true;
    await this.loadCatalogs();
  }

  async openBulkAssign(): Promise<void> {
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

  get annualSummary() {
    const projectDays = new Map<number, number>();
    const typeDays = new Map<number, number>();
    let workingDays = 0;
    let workedDays = 0;

    for (const month of this.state.calendar) {
      for (const day of month.days) {
        if (!day) continue;
        if (!day.typings.some(type => type.nombre === 'Festivo') &&
            !day.assignments.some(project => project.nombre === 'Vacaciones')) workingDays++;
        if (day.assignments.some(project => project.laborable)) workedDays++;
        for (const id of new Set(day.assignments.map(project => project.proyecto_id))) {
          projectDays.set(id, (projectDays.get(id) ?? 0) + 1);
        }
        for (const id of new Set(day.typings.map(type => type.tipo_id))) {
          typeDays.set(id, (typeDays.get(id) ?? 0) + 1);
        }
      }
    }

    return {
      workingDays,
      workedDays,
      projects: this.projects.map(project => ({ ...project, days: projectDays.get(project.proyecto_id) ?? 0 })),
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
    const date = this.dismissDay();
    if (date) document.querySelector<HTMLButtonElement>(`.day[aria-label="${date}"]`)?.focus();
  }

  private dismissDay(): string | undefined {
    const date = this.selectedDay?.date;
    if (date) this.selectedDates.delete(date);
    this.selectedDay = null;
    return date;
  }

  openItem(view: 'proyectos' | 'tipos', id: number): void {
    this.state.editTarget = { view, id };
    this.state.menuOpen = false;
    this.state.view = view;
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
    return day.assignments.every(item => item.es_prevision)
      ? `color-mix(in srgb, ${color} 80%, white)` : color;
  }

  async createYear(form: NgForm): Promise<void> {
    if (form.invalid || !Number.isInteger(this.newYear)) return;
    await this.state.run(async () => {
      await this.state.request('POST', '/api/new_year', { year: this.newYear });
      await this.state.loadYears(this.newYear);
      this.state.view = 'calendar';
      this.state.message = 'Año creado.';
    });
  }
}

import { ComponentFixture, TestBed, fakeAsync, flushMicrotasks, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { By } from '@angular/platform-browser';
import { NgForm } from '@angular/forms';
import { App } from './app';
import { LoginComponent } from './login/login';
import { CalendarComponent } from './calendar/calendar';
import { ProjectsComponent } from './projects/projects';
import { UsersComponent } from './users/users';
import { DateTypesComponent } from './date-types/date-types';

describe('Calendar application', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    localStorage.removeItem('calendar_token');
    localStorage.removeItem('calendar_expiry');
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()]
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    localStorage.removeItem('calendar_token');
    localStorage.removeItem('calendar_expiry');
  });

  function login(fixture: ComponentFixture<App>): void {
    const loginComponent: LoginComponent = fixture.debugElement.query(By.directive(LoginComponent)).componentInstance;
    loginComponent.loginName = 'admin';
    loginComponent.loginPassword = 'password123';
    void loginComponent.login({ invalid: false } as NgForm);
    http.expectOne('/api/auth/login').flush({ access_token: 'token', expires_in: 3600 });
    flushMicrotasks();
    const me = http.expectOne('/api/me');
    expect(me.request.headers.get('Authorization')).toBe('Bearer token');
    me.flush({ usuario_id: 1, activo: true, es_administrador: true });
    flushMicrotasks();
    http.expectOne('/api/get_years').flush({ years: [2025, 2026] });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({
      asignaciones: [{ fecha: '2026-03-01', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', es_prevision: false }],
      tipados: [
        { fecha: '2026-01-01', tipo_id: 1, nombre: 'Festivo', color: '#FF0000', en_borde: false },
        { fecha: '2026-01-02', tipo_id: 2, nombre: 'Especial', color: '#00AA00', en_borde: true }
      ]
    });
    flushMicrotasks();
  }

  function backgroundRgb(element: Element): number[] {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d')!;
    context.fillStyle = getComputedStyle(element).backgroundColor;
    context.fillRect(0, 0, 1, 1);
    return Array.from(context.getImageData(0, 0, 1, 1).data).slice(0, 3);
  }

  it('authenticates, displays the calendar and loads a selected year', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Iniciar sesión');
    expect(fixture.nativeElement.textContent).not.toContain('Configuración');
    login(fixture);
    fixture.detectChanges();
    expect(localStorage.getItem('calendar_token')).toBe('token');
    expect(fixture.nativeElement.querySelector('.year-title').textContent.trim()).toBe('2026');
    expect(fixture.nativeElement.textContent).not.toContain('Festivo');
    expect(fixture.nativeElement.textContent).not.toContain('Trabajo');
    const coloredNumber = fixture.nativeElement.querySelector('.day[aria-label="2026-01-01"] .day-number');
    const borderedDay = fixture.nativeElement.querySelector('.day[aria-label="2026-01-02"]');
    expect(getComputedStyle(coloredNumber).color).toBe('rgb(255, 0, 0)');
    expect(getComputedStyle(borderedDay).outlineColor).toBe('rgb(0, 170, 0)');
    expect(getComputedStyle(borderedDay).outlineWidth).toBe('2px');
    void fixture.componentInstance.state.changeYear('2025');
    http.expectOne('/api/calendario/2025').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.year-title').textContent.trim()).toBe('2025');
    expect(fixture.nativeElement.textContent).not.toContain('Trabajo');
    fixture.componentInstance.state.logout();
  }));

  it('opens a month and returns to the annual calendar using navigation', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const root: HTMLElement = fixture.nativeElement;
    expect(root.querySelectorAll('.month-card').length).toBe(12);
    root.querySelector<HTMLButtonElement>('.day[aria-label="2026-03-01"]')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    root.querySelector<HTMLButtonElement>('[aria-label="Ver Enero 2026"]')!.click();
    fixture.detectChanges();
    http.expectNone('/api/calendario/2026');
    expect(root.querySelector('h2')?.textContent).toBe('Calendario mensual');
    expect(root.querySelectorAll('.month-card').length).toBe(1);
    expect(root.querySelector('.month-card')?.getAttribute('aria-label')).toBe('Enero 2026');
    expect(root.querySelectorAll('.day').length).toBe(31);
    expect(getComputedStyle(root.querySelector('.day[aria-label="2026-01-02"]')!).outlineWidth).toBe('2px');
    root.querySelector<HTMLButtonElement>('.day[aria-label="2026-01-01"]')!.click();
    http.expectOne('/api/proyectos').flush([]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelector('.day-panel')?.textContent).toContain('Festivo');
    const calendarNav = Array.from(root.querySelectorAll<HTMLButtonElement>('.navigation .nav-link'))
      .find(button => button.textContent?.trim() === 'Calendario')!;
    calendarNav.click();
    fixture.detectChanges();
    expect(root.querySelector('h2')?.textContent).toBe('Calendario anual');
    expect(root.querySelectorAll('.month-card').length).toBe(12);
    expect(root.querySelector('.day-panel')).toBeNull();
    expect(root.querySelector('.day[aria-label="2026-01-01"]')?.getAttribute('aria-pressed')).toBe('false');
    root.querySelector<HTMLButtonElement>('[aria-label="Ver Marzo 2026"]')!.click();
    fixture.detectChanges();
    expect(root.querySelectorAll('.month-card').length).toBe(1);
    expect(getComputedStyle(root.querySelector('.day[aria-label="2026-03-01"]')!).backgroundColor).toBe('rgb(18, 52, 86)');
    root.querySelector<HTMLButtonElement>('.section-heading .secondary')!.click();
    fixture.detectChanges();
    expect(root.querySelectorAll('.month-card').length).toBe(12);
    fixture.componentInstance.state.logout();
  }));

  it('shows annual totals by distinct day, including forecasts, and follows the selected year', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    const state = fixture.componentInstance.state;
    state.years = [2024, 2025, 2026];
    void state.changeYear('2024');
    const work = { proyecto_id: 1, nombre: 'Trabajo', color: '#123456', laborable: true };
    const vacation = { proyecto_id: 2, nombre: 'Vacaciones', color: '#FF7800', laborable: false };
    const other = { proyecto_id: 3, nombre: 'Otro', color: '#000000', laborable: true };
    http.expectOne('/api/calendario/2024').flush({
      asignaciones: [
        { ...work, fecha: '2024-01-01', es_prevision: false },
        { ...work, fecha: '2024-01-01', es_prevision: true },
        { ...vacation, fecha: '2024-01-01', es_prevision: false },
        { ...vacation, fecha: '2024-01-02', es_prevision: true },
        { ...work, fecha: '2024-01-03', es_prevision: true },
        { ...other, fecha: '2024-01-03', es_prevision: false },
        { ...work, fecha: '2024-01-06', es_prevision: false }
      ],
      tipados: [
        { fecha: '2024-01-01', tipo_id: 1, nombre: 'Festivo', color: '#FF0000', en_borde: false },
        { fecha: '2024-01-03', tipo_id: 1, nombre: 'Festivo', color: '#FF0000', en_borde: false },
        { fecha: '2024-01-03', tipo_id: 2, nombre: 'Especial', color: '#00AA00', en_borde: true }
      ]
    });
    flushMicrotasks();
    fixture.detectChanges();
    const root: HTMLElement = fixture.nativeElement;
    root.querySelector<HTMLButtonElement>('#annual-info-button')!.click();
    http.expectOne('/api/proyectos').flush([
      { ...work, descripcion: '', duracion: 10, restantes: 7 },
      { ...vacation, descripcion: '', duracion: null, restantes: null },
      { ...other, descripcion: '', duracion: 0, restantes: 0 }
    ]);
    http.expectOne('/api/tipos-fecha').flush([
      { tipo_id: 1, nombre: 'Festivo', color: '#FF0000', en_borde: false },
      { tipo_id: 2, nombre: 'Especial', color: '#00AA00', en_borde: true },
      { tipo_id: 3, nombre: 'Sin asignar', color: '#000000', en_borde: true }
    ]);
    flushMicrotasks();
    fixture.detectChanges();
    const panel = () => root.querySelector<HTMLElement>('.annual-info')!;
    expect(panel().textContent).toContain('Días laborables: 363');
    expect(panel().textContent).toContain('Días trabajados: 3');
    const types = panel().querySelector('[aria-labelledby="annual-types-title"]')!;
    const typeRows = types.querySelectorAll('.day-panel-item');
    expect(typeRows[0].textContent).toContain('Festivo');
    expect(typeRows[0].textContent).toContain('2 días');
    expect(typeRows[1].textContent).toContain('Especial');
    expect(typeRows[1].textContent).toContain('1 día');
    expect(typeRows[2].textContent).toContain('Sin asignar');
    expect(typeRows[2].textContent).toContain('0 días');
    const projects = panel().querySelectorAll('.annual-project');
    expect(projects[0].textContent).toContain('Duración inicial: 10');
    expect(projects[0].textContent).toContain('Días restantes: 7');
    expect(projects[0].textContent).toContain('Días asignados: 3');
    expect(projects[1].textContent).toContain('Días asignados: 2');
    expect(projects[1].textContent).toContain('Duración inicial: —');

    void state.changeYear('2025');
    fixture.detectChanges();
    expect(panel().textContent).toContain('Cargando información anual');
    http.expectOne('/api/calendario/2025').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(panel().textContent).toContain('Información anual 2025');
    expect(panel().textContent).toContain('Días laborables: 365');
    expect(panel().textContent).toContain('Días trabajados: 0');
    expect(panel().querySelector('.annual-project')?.textContent).toContain('Días asignados: 0');

    root.querySelector<HTMLButtonElement>('[aria-label="Ver Enero 2025"]')!.click();
    fixture.detectChanges();
    expect(root.querySelector('#annual-info-button')).toBeNull();
    expect(root.querySelector('.annual-info')).toBeNull();
    root.querySelector<HTMLButtonElement>('.section-heading .secondary')!.click();
    fixture.detectChanges();
    expect(root.querySelector('#annual-info-button')).not.toBeNull();
    state.logout();
  }));

  it('allows retrying annual catalog loading after an error', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const root: HTMLElement = fixture.nativeElement;
    root.querySelector<HTMLButtonElement>('#annual-info-button')!.click();
    http.expectOne('/api/proyectos').flush({ error: 'Error al cargar proyectos' }, { status: 500, statusText: 'Error' });
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelector('.annual-info')?.textContent).toContain('Error al cargar proyectos');
    root.querySelector<HTMLButtonElement>('.annual-info .secondary:not([aria-label])')!.click();
    http.expectOne('/api/proyectos').flush([]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelector('.annual-info')?.textContent).toContain('Días laborables: 364');
    root.querySelector<HTMLButtonElement>('[aria-label="Cerrar información anual"]')!.click();
    fixture.detectChanges();
    expect(root.querySelector('.annual-info')).toBeNull();
    expect(document.activeElement?.id).toBe('annual-info-button');
    fixture.componentInstance.state.logout();
  }));

  it('keeps the selected month when switching years', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const root: HTMLElement = fixture.nativeElement;
    root.querySelector<HTMLButtonElement>('[aria-label="Ver Febrero 2026"]')!.click();
    fixture.detectChanges();
    void fixture.componentInstance.state.changeYear('2025');
    http.expectOne('/api/calendario/2025').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelector('.month-card')?.getAttribute('aria-label')).toBe('Febrero 2025');
    expect(root.querySelectorAll('.day').length).toBe(28);
    expect(root.querySelector('.day[aria-label="2025-02-01"]')).not.toBeNull();
    fixture.componentInstance.state.logout();
  }));

  it('colors days by distinct projects without displaying assignment badges', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    void fixture.componentInstance.state.changeYear('2025');
    http.expectOne('/api/calendario/2025').flush({
      asignaciones: [
        { fecha: '2025-01-02', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', es_prevision: false },
        { fecha: '2025-01-03', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', es_prevision: false },
        { fecha: '2025-01-03', proyecto_id: 2, nombre: 'Otro', color: '#abcdef', es_prevision: true },
        { fecha: '2025-01-04', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', es_prevision: false },
        { fecha: '2025-01-04', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', es_prevision: true },
        { fecha: '2025-01-05', proyecto_id: 3, nombre: 'Sin color', color: null, es_prevision: false },
        { fecha: '2025-01-06', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', es_prevision: true },
        { fecha: '2025-01-07', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', es_prevision: true },
        { fecha: '2025-01-07', proyecto_id: 2, nombre: 'Otro', color: '#abcdef', es_prevision: true }
      ],
      tipados: [
        { fecha: '2025-01-03', tipo_id: 1, nombre: 'Festivo', color: '#FF0000', en_borde: false },
        { fecha: '2025-01-03', tipo_id: 2, nombre: 'Especial', color: '#00AA00', en_borde: true }
      ]
    });
    flushMicrotasks();
    fixture.detectChanges();
    const day = (date: string): HTMLElement => fixture.nativeElement.querySelector(`.day[aria-label="${date}"]`);
    expect(getComputedStyle(day('2025-01-01')).backgroundColor).toBe('rgba(0, 0, 0, 0)');
    expect(getComputedStyle(day('2025-01-02')).backgroundColor).toBe('rgb(18, 52, 86)');
    expect(getComputedStyle(day('2025-01-03')).backgroundColor).toBe('rgb(44, 129, 58)');
    expect(getComputedStyle(day('2025-01-04')).backgroundColor).toBe('rgb(18, 52, 86)');
    expect(getComputedStyle(day('2025-01-05')).backgroundColor).toBe('rgb(156, 163, 175)');
    expect(backgroundRgb(day('2025-01-06'))).toEqual([65, 93, 120]);
    expect(backgroundRgb(day('2025-01-07'))).toEqual([86, 154, 97]);
    expect(getComputedStyle(day('2025-01-03')).outlineColor).toBe('rgb(0, 170, 0)');
    expect(getComputedStyle(day('2025-01-03').querySelector('.day-number')!).color).toBe('rgb(255, 0, 0)');
    expect(day('2025-01-03').textContent?.trim()).toBe('3');
    expect(day('2025-01-03').querySelectorAll('.event').length).toBe(0);
    fixture.componentInstance.state.logout();
  }));

  it('selects multiple days with Shift without opening the panel', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const day = (date: string): HTMLButtonElement => fixture.nativeElement.querySelector(`.day[aria-label="${date}"]`);
    const shiftClick = (date: string) => day(date).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    shiftClick('2026-01-02');
    shiftClick('2026-03-01');
    shiftClick('2026-01-02');
    fixture.detectChanges();
    http.expectNone('/api/proyectos');
    http.expectNone('/api/tipos-fecha');
    expect(fixture.nativeElement.querySelector('.day-panel')).toBeNull();
    expect(day('2026-01-02').getAttribute('aria-pressed')).toBe('true');
    expect(day('2026-03-01').getAttribute('aria-pressed')).toBe('true');
    expect(day('2026-01-01').getAttribute('aria-pressed')).toBe('false');
    expect(day('2026-01-02').querySelector('.selection-mark')).not.toBeNull();
    expect(getComputedStyle(day('2026-01-02')).outlineColor).toBe('rgb(0, 170, 0)');
    expect(getComputedStyle(day('2026-03-01')).backgroundColor).toBe('rgb(18, 52, 86)');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(day('2026-01-02').getAttribute('aria-pressed')).toBe('true');
    expect(day('2026-03-01').getAttribute('aria-pressed')).toBe('true');

    void fixture.componentInstance.state.loadCalendar(2026);
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(day('2026-01-02').getAttribute('aria-pressed')).toBe('true');
    expect(day('2026-03-01').getAttribute('aria-pressed')).toBe('true');

    day('2026-01-03').click();
    http.expectOne('/api/proyectos').flush([]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel')).not.toBeNull();
    expect(day('2026-01-02').getAttribute('aria-pressed')).toBe('false');
    expect(day('2026-03-01').getAttribute('aria-pressed')).toBe('false');
    expect(day('2026-01-03').getAttribute('aria-pressed')).toBe('true');
    shiftClick('2026-01-04');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel')).toBeNull();
    expect(day('2026-01-03').getAttribute('aria-pressed')).toBe('false');
    expect(day('2026-01-04').getAttribute('aria-pressed')).toBe('true');
    day('2026-01-04').click();
    http.expectOne('/api/proyectos').flush([]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    shiftClick('2026-01-04');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel')).toBeNull();
    expect(day('2026-01-04').getAttribute('aria-pressed')).toBe('true');

    void fixture.componentInstance.state.changeYear('2025');
    http.expectOne('/api/calendario/2025').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    void fixture.componentInstance.state.changeYear('2026');
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(day('2026-01-03').getAttribute('aria-pressed')).toBe('false');
    expect(day('2026-01-04').getAttribute('aria-pressed')).toBe('false');
    fixture.componentInstance.state.logout();
  }));

  it('assigns selected projects and types to multiple days in the annual view', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const root: HTMLElement = fixture.nativeElement;
    const shiftClick = (date: string) => root.querySelector<HTMLButtonElement>(`.day[aria-label="${date}"]`)!
      .dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    expect(root.querySelector('#bulk-assign-button')).toBeNull();
    shiftClick('2026-02-01');
    fixture.detectChanges();
    expect(root.querySelector('#bulk-assign-button')).toBeNull();
    shiftClick('2026-02-02');
    fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('#bulk-assign-button')!.click();
    const project = { proyecto_id: 1, nombre: 'Trabajo', descripcion: '', duracion: 10, restantes: 5, color: '#123456', laborable: true };
    const type = { tipo_id: 2, nombre: 'Especial', descripcion: '', color: '#00AA00', en_borde: true };
    http.expectOne('/api/proyectos').flush([project]);
    http.expectOne('/api/tipos-fecha').flush([type]);
    flushMicrotasks();
    fixture.detectChanges();
    const panel = root.querySelector<HTMLElement>('.bulk-assign')!;
    expect(panel.textContent).toContain('Asignar a 2 días');
    const submit = panel.querySelector<HTMLButtonElement>('.primary')!;
    expect(submit.disabled).toBeTrue();
    const forecastOption = panel.querySelector<HTMLInputElement>('input[name="bulkForecast"]')!;
    expect(forecastOption.checked).toBeFalse();
    expect(forecastOption.closest('label')?.textContent).toContain('Asignar proyectos en previsión');
    panel.querySelector<HTMLInputElement>('input[name="bulkProject"]')!.click();
    forecastOption.click();
    panel.querySelector<HTMLInputElement>('[aria-labelledby="bulk-types-title"] input')!.click();
    fixture.detectChanges();
    expect(submit.disabled).toBeFalse();
    submit.click();
    const request = http.expectOne('/api/asignaciones/multiples');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      fechas: ['2026-02-01', '2026-02-02'], proyectos: [1], tipos: [2], es_prevision: true
    });
    request.flush({ fechas: 2, asignaciones: 2, tipados: 2 }, { status: 201, statusText: 'Created' });
    flushMicrotasks();
    const asignaciones = ['2026-02-01', '2026-02-02'].map(fecha => ({
      fecha, proyecto_id: 1, nombre: 'Trabajo', color: '#123456', laborable: true, es_prevision: true
    }));
    const tipados = ['2026-02-01', '2026-02-02'].map(fecha => ({
      fecha, tipo_id: 2, nombre: 'Especial', color: '#00AA00', en_borde: true
    }));
    http.expectOne('/api/calendario/2026').flush({ asignaciones, tipados });
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelector('.bulk-assign')).toBeNull();
    expect(root.querySelector('#bulk-assign-button')).toBeNull();
    expect(root.querySelector('.day[aria-label="2026-02-01"]')?.getAttribute('aria-pressed')).toBe('false');
    expect(backgroundRgb(root.querySelector('.day[aria-label="2026-02-01"]')!)).toEqual([65, 93, 120]);
    expect(getComputedStyle(root.querySelector('.day[aria-label="2026-02-02"]')!).outlineColor).toBe('rgb(0, 170, 0)');
    fixture.componentInstance.state.logout();
  }));

  it('keeps the selection and choices when a bulk assignment conflicts', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const root: HTMLElement = fixture.nativeElement;
    for (const date of ['2026-02-01', '2026-02-02']) {
      root.querySelector<HTMLButtonElement>(`.day[aria-label="${date}"]`)!
        .dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    }
    fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('#bulk-assign-button')!.click();
    http.expectOne('/api/proyectos').flush([{ proyecto_id: 1, nombre: 'Trabajo', laborable: true }]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    const panel = root.querySelector<HTMLElement>('.bulk-assign')!;
    panel.querySelector<HTMLInputElement>('input[name="bulkProject"]')!.click();
    fixture.detectChanges();
    panel.querySelector<HTMLButtonElement>('.primary')!.click();
    const request = http.expectOne('/api/asignaciones/multiples');
    expect(request.request.body.es_prevision).toBeFalse();
    request.flush({ error: '2026-02-02: el proyecto 1 ya está asignado' }, { status: 409, statusText: 'Conflict' });
    flushMicrotasks();
    fixture.detectChanges();
    expect(panel.textContent).toContain('2026-02-02');
    expect(panel.querySelector<HTMLInputElement>('input[name="bulkProject"]')!.checked).toBeTrue();
    expect(root.querySelector('.day[aria-label="2026-02-01"]')?.getAttribute('aria-pressed')).toBe('true');
    http.expectNone('/api/calendario/2026');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(root.querySelector('.bulk-assign')).toBeNull();
    expect(document.activeElement?.id).toBe('bulk-assign-button');
    root.querySelector<HTMLButtonElement>('[aria-label="Ver Febrero 2026"]')!.click();
    fixture.detectChanges();
    expect(root.querySelector('#bulk-assign-button')).toBeNull();
    fixture.componentInstance.state.logout();
  }));

  it('selects a day and adds and removes project and type assignments', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const project = { proyecto_id: 1, nombre: 'Trabajo', descripcion: '', duracion: null, restantes: null, color: '#123456', laborable: true };
    const type = { tipo_id: 2, nombre: 'Especial', descripcion: '', color: '#00AA00', en_borde: true };
    const assignment = { fecha: '2026-01-03', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', laborable: true, es_prevision: true };
    const typing = { fecha: '2026-01-03', tipo_id: 2, nombre: 'Especial', color: '#00AA00', en_borde: true };
    fixture.nativeElement.querySelector('.day[aria-label="2026-01-03"]').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.day-panel').length).toBe(1);
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('2026-01-03');
    http.expectOne('/api/proyectos').flush([project]);
    http.expectOne('/api/tipos-fecha').flush([type]);
    flushMicrotasks();
    fixture.detectChanges();
    const calendar: CalendarComponent = fixture.debugElement.query(By.directive(CalendarComponent)).componentInstance;
    calendar.selectedProjectId = 1;
    calendar.forecast = true;
    fixture.detectChanges();
    const buttons = () => Array.from(fixture.nativeElement.querySelectorAll('.day-panel button')) as HTMLButtonElement[];
    buttons().find(button => button.textContent?.trim() === 'Añadir proyecto')!.click();
    const addProject = http.expectOne('/api/asignaciones');
    expect(addProject.request.body).toEqual({ fecha: '2026-01-03', proyecto_id: 1, es_prevision: true });
    addProject.flush({}, { status: 201, statusText: 'Created' });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [assignment], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('Trabajo · previsión');
    expect(backgroundRgb(fixture.nativeElement.querySelector('.day[aria-label="2026-01-03"]'))).toEqual([65, 93, 120]);
    expect(calendar.canAddProject(calendar.selectedDay!)).toBeFalse();
    calendar.selectedTypeId = 2;
    fixture.detectChanges();
    buttons().find(button => button.textContent?.trim() === 'Añadir tipo')!.click();
    const addType = http.expectOne('/api/tipados');
    expect(addType.request.body).toEqual({ fecha: '2026-01-03', tipo_id: 2 });
    addType.flush({}, { status: 201, statusText: 'Created' });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [assignment], tipados: [typing] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(calendar.canAddType(calendar.selectedDay!)).toBeFalse();
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('Especial · borde');
    fixture.nativeElement.querySelector('[aria-label="Eliminar Trabajo previsión"]').click();
    const removeProject = http.expectOne('/api/asignaciones/2026-01-03/1/true');
    expect(removeProject.request.method).toBe('DELETE');
    removeProject.flush(null, { status: 204, statusText: 'No Content' });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [typing] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(getComputedStyle(fixture.nativeElement.querySelector('.day[aria-label="2026-01-03"]')).backgroundColor)
      .toBe('rgba(0, 0, 0, 0)');
    fixture.nativeElement.querySelector('[aria-label="Eliminar Especial"]').click();
    const removeType = http.expectOne('/api/tipados/2026-01-03/2');
    expect(removeType.request.method).toBe('DELETE');
    removeType.flush(null, { status: 204, statusText: 'No Content' });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('No hay tipos asignados');
    fixture.nativeElement.querySelector('[aria-label="Cerrar detalle del día"]').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel')).toBeNull();
    expect(fixture.nativeElement.querySelector('.day[aria-label="2026-01-03"]').getAttribute('aria-pressed')).toBe('false');
    expect(fixture.nativeElement.querySelector('.day[aria-label="2026-01-03"] .selection-mark')).toBeNull();
    fixture.componentInstance.state.logout();
  }));

  it('confirms forecasts, preserves them on error and merges an existing confirmation', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    const state = fixture.componentInstance.state;
    const project = { proyecto_id: 1, nombre: 'Trabajo', descripcion: '', duracion: null, restantes: null, color: '#123456', laborable: true };
    const forecast = { fecha: '2026-01-03', proyecto_id: 1, nombre: 'Trabajo', color: '#123456', laborable: true, es_prevision: true };
    const confirmed = { ...forecast, es_prevision: false };
    void state.loadCalendar(2026);
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [forecast], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    const root: HTMLElement = fixture.nativeElement;
    root.querySelector<HTMLButtonElement>('.day[aria-label="2026-01-03"]')!.click();
    http.expectOne('/api/proyectos').flush([project]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    const confirmButton = () => root.querySelector<HTMLButtonElement>('[aria-label="Confirmar previsión de Trabajo"]')!;
    confirmButton().click();
    fixture.detectChanges();
    expect(confirmButton().disabled).toBeTrue();
    http.expectOne('/api/asignaciones/2026-01-03/1/confirmar')
      .flush({ error: 'No se pudo confirmar' }, { status: 500, statusText: 'Error' });
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelector('.day-panel')?.textContent).toContain('No se pudo confirmar');
    expect(confirmButton()).not.toBeNull();
    expect(backgroundRgb(root.querySelector('.day[aria-label="2026-01-03"]')!)).toEqual([65, 93, 120]);
    confirmButton().click();
    const request = http.expectOne('/api/asignaciones/2026-01-03/1/confirmar');
    expect(request.request.method).toBe('POST');
    request.flush({ ...confirmed, usuario_id: 1 });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [confirmed], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelector('[aria-label="Confirmar previsión de Trabajo"]')).toBeNull();
    expect(getComputedStyle(root.querySelector('.day[aria-label="2026-01-03"]')!).backgroundColor).toBe('rgb(18, 52, 86)');

    void state.loadCalendar(2026);
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [confirmed, forecast], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('.day[aria-label="2026-01-03"]')!.click();
    http.expectOne('/api/proyectos').flush([project]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    confirmButton().click();
    http.expectOne('/api/asignaciones/2026-01-03/1/confirmar').flush({ ...confirmed, usuario_id: 1 });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [confirmed], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(root.querySelectorAll('.day-panel-item .item-link').length).toBe(1);
    expect(root.querySelector('[aria-label="Confirmar previsión de Trabajo"]')).toBeNull();
    state.logout();
  }));

  it('opens the linked type and selects it for editing', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.day[aria-label="2026-01-01"]').click();
    http.expectOne('/api/proyectos').flush([]);
    const type = { tipo_id: 1, nombre: 'Festivo', descripcion: '', color: '#FF0000', en_borde: false };
    http.expectOne('/api/tipos-fecha').flush([type]);
    flushMicrotasks();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.day-panel .item-link').click();
    fixture.detectChanges();
    http.expectOne('/api/tipos-fecha').flush([type]);
    flushMicrotasks();
    fixture.detectChanges();
    const types: DateTypesComponent = fixture.debugElement.query(By.directive(DateTypesComponent)).componentInstance;
    expect(types.editingId).toBe(1);
    expect(types.typeForm.nombre).toBe('Festivo');
    fixture.componentInstance.state.logout();
  }));

  it('opens the linked project and closes the panel on a year change', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    const project = { proyecto_id: 1, nombre: 'Trabajo', descripcion: '', duracion: null, restantes: null, color: '#123456', laborable: true };
    fixture.nativeElement.querySelector('.day[aria-label="2026-03-01"]').click();
    http.expectOne('/api/proyectos').flush([project]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.day-panel .item-link').click();
    fixture.detectChanges();
    http.expectOne('/api/proyectos').flush([project]);
    flushMicrotasks();
    fixture.detectChanges();
    const projects: ProjectsComponent = fixture.debugElement.query(By.directive(ProjectsComponent)).componentInstance;
    expect(projects.editingId).toBe(1);
    fixture.componentInstance.navigate('calendar');
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.day[aria-label="2026-03-01"]').click();
    http.expectOne('/api/proyectos').flush([project]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    void fixture.componentInstance.state.changeYear('2025');
    http.expectOne('/api/calendario/2025').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel')).toBeNull();
    fixture.componentInstance.state.logout();
  }));

  it('allows retrying a calendar refresh after an assignment was saved', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.day[aria-label="2026-01-01"]').click();
    http.expectOne('/api/proyectos').flush([]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('[aria-label="Eliminar Festivo"]').click();
    http.expectOne('/api/tipados/2026-01-01/1').flush(null, { status: 204, statusText: 'No Content' });
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush(
      { error: 'Error al cargar calendario' }, { status: 500, statusText: 'Server Error' }
    );
    flushMicrotasks();
    fixture.detectChanges();
    const panel = fixture.nativeElement.querySelector('.day-panel');
    expect(panel.textContent).toContain('La asignación se ha guardado');
    expect(panel.textContent).toContain('Error al cargar calendario');
    const retry = Array.from(panel.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find(button => button.textContent?.includes('Reintentar actualización'))!;
    retry.click();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('Calendario actualizado');
    expect(fixture.nativeElement.querySelector('.day[aria-label="2026-01-01"]')).not.toBeNull();
    fixture.componentInstance.state.logout();
  }));

  it('shows assignment failures in the day panel without changing the day', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.day[aria-label="2026-01-01"]').click();
    http.expectOne('/api/proyectos').flush([]);
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('[aria-label="Eliminar Festivo"]').click();
    http.expectOne('/api/tipados/2026-01-01/1').flush(
      { error: 'No se ha podido eliminar' }, { status: 409, statusText: 'Conflict' }
    );
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('No se ha podido eliminar');
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('Festivo');
    fixture.componentInstance.state.logout();
  }));

  it('prevents conflicting date types and closes the panel with Escape', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    login(fixture);
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.day[aria-label="2026-01-01"]').click();
    http.expectOne('/api/proyectos').flush([]);
    http.expectOne('/api/tipos-fecha').flush([
      { tipo_id: 3, nombre: 'Otro', descripcion: '', color: '#123456', en_borde: false },
      { tipo_id: 4, nombre: 'Borde', descripcion: '', color: '#654321', en_borde: true }
    ]);
    flushMicrotasks();
    fixture.detectChanges();
    const calendar: CalendarComponent = fixture.debugElement.query(By.directive(CalendarComponent)).componentInstance;
    calendar.selectedTypeId = 3;
    fixture.detectChanges();
    expect(calendar.canAddType(calendar.selectedDay!)).toBeFalse();
    expect(fixture.nativeElement.querySelector('.day-panel').textContent).toContain('Elimina el existente');
    calendar.selectedTypeId = 4;
    expect(calendar.canAddType(calendar.selectedDay!)).toBeTrue();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.day-panel')).toBeNull();
    expect(fixture.nativeElement.querySelector('.day[aria-label="2026-01-01"]').getAttribute('aria-pressed')).toBe('false');
    fixture.componentInstance.state.logout();
  }));

  it('restores a valid stored session and clears it when the token is rejected', fakeAsync(() => {
    localStorage.setItem('calendar_token', 'saved');
    localStorage.setItem('calendar_expiry', String(Date.now() + 3600000));
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    http.expectOne('/api/me').flush({ error: 'Token inválido' }, { status: 401, statusText: 'Unauthorized' });
    flushMicrotasks();
    fixture.detectChanges();
    expect(localStorage.getItem('calendar_token')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Inicia sesión de nuevo');
    expect(fixture.nativeElement.textContent).not.toContain('Configuración');
  }));

  it('creates a year and hides the application when the session expires', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const app = fixture.componentInstance;
    login(fixture);
    fixture.detectChanges();
    const calendar: CalendarComponent = fixture.debugElement.query(By.directive(CalendarComponent)).componentInstance;
    calendar.newYear = 2027;
    void calendar.createYear({ invalid: false } as NgForm);
    const request = http.expectOne('/api/new_year');
    expect(request.request.body).toEqual({ year: 2027 });
    request.flush({ fecha: '2027-01-01', tipo_id: 1, usuario_id: 1 });
    flushMicrotasks();
    http.expectOne('/api/get_years').flush({ years: [2025, 2026, 2027] });
    flushMicrotasks();
    http.expectOne('/api/calendario/2027').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.year-title').textContent.trim()).toBe('2027');
    tick(3600000);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('La sesión ha caducado');
    expect(localStorage.getItem('calendar_token')).toBeNull();
  }));

  it('creates and edits projects using the backend and refreshes the year', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const app = fixture.componentInstance;
    login(fixture);
    app.navigate('proyectos');
    fixture.detectChanges();
    http.expectOne('/api/proyectos').flush([]);
    flushMicrotasks();
    const projects: ProjectsComponent = fixture.debugElement.query(By.directive(ProjectsComponent)).componentInstance;
    fixture.detectChanges();
    const laborable = fixture.nativeElement.querySelector('input[name="laborable"]') as HTMLInputElement;
    expect(laborable.checked).toBeTrue();
    projects.projectForm.nombre = 'Proyecto A';
    void projects.saveProject({ invalid: false } as NgForm);
    const created = http.expectOne('/api/proyectos');
    expect(created.request.method).toBe('POST');
    expect(created.request.body.nombre).toBe('Proyecto A');
    expect(created.request.body.laborable).toBeTrue();
    created.flush({ proyecto_id: 1 });
    flushMicrotasks();
    const project = { proyecto_id: 1, nombre: 'Proyecto A', descripcion: '', duracion: null, restantes: null, color: '#4f46e5', laborable: true };
    http.expectOne('/api/proyectos').flush([project]);
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    projects.editProject(project);
    projects.projectForm.nombre = 'Proyecto B';
    fixture.detectChanges();
    laborable.click();
    expect(projects.projectForm.laborable).toBeFalse();
    void projects.saveProject({ invalid: false } as NgForm);
    const updated = http.expectOne('/api/proyectos/1');
    expect(updated.request.method).toBe('PATCH');
    expect(updated.request.body.nombre).toBe('Proyecto B');
    expect(updated.request.body.laborable).toBeFalse();
    updated.flush({ ...project, nombre: 'Proyecto B', laborable: false });
    flushMicrotasks();
    http.expectOne('/api/proyectos').flush([{ ...project, nombre: 'Proyecto B', laborable: false }]);
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Proyecto B');
    app.state.logout();
  }));

  it('creates a user and sends only changed fields when editing', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const app = fixture.componentInstance;
    login(fixture);
    app.navigate('usuarios');
    fixture.detectChanges();
    http.expectOne('/api/usuarios').flush([]);
    flushMicrotasks();
    const users: UsersComponent = fixture.debugElement.query(By.directive(UsersComponent)).componentInstance;
    users.userForm.nombre = 'Ana';
    users.userForm.nombre_usuario = 'ana';
    users.userForm.password = 'password123';
    void users.saveUser({ invalid: false } as NgForm);
    const created = http.expectOne('/api/usuarios');
    expect(created.request.body.nombre_usuario).toBe('ana');
    expect(created.request.body.password).toBe('password123');
    created.flush({ usuario_id: 2 });
    flushMicrotasks();
    http.expectOne('/api/me').flush({ usuario_id: 1, activo: true, es_administrador: true });
    flushMicrotasks();
    const user = { usuario_id: 2, nombre: 'Ana', apellido1: null, apellido2: null, activo: true, es_administrador: false, nombre_usuario: 'ana' };
    http.expectOne('/api/usuarios').flush([user]);
    flushMicrotasks();
    users.editUser(user);
    users.userForm.nombre = 'Ana María';
    void users.saveUser({ invalid: false } as NgForm);
    const updated = http.expectOne('/api/usuarios/2');
    expect(updated.request.method).toBe('PATCH');
    expect(updated.request.body).toEqual({ nombre: 'Ana María' });
    updated.flush({ ...user, nombre: 'Ana María' });
    flushMicrotasks();
    http.expectOne('/api/me').flush({ usuario_id: 1, activo: true, es_administrador: true });
    flushMicrotasks();
    http.expectOne('/api/usuarios').flush([{ ...user, nombre: 'Ana María' }]);
    flushMicrotasks();
    expect(users.users[0].nombre).toBe('Ana María');
    app.state.logout();
  }));

  it('creates and edits date types through the backend', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const app = fixture.componentInstance;
    login(fixture);
    app.navigate('tipos');
    fixture.detectChanges();
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    const types: DateTypesComponent = fixture.debugElement.query(By.directive(DateTypesComponent)).componentInstance;
    types.typeForm.nombre = 'Vacaciones';
    void types.saveType({ invalid: false } as NgForm);
    const created = http.expectOne('/api/tipos-fecha');
    expect(created.request.method).toBe('POST');
    expect(created.request.body.en_borde).toBe(false);
    created.flush({ tipo_id: 2 });
    flushMicrotasks();
    const type = { tipo_id: 2, nombre: 'Vacaciones', descripcion: '', color: '#ef4444', en_borde: false };
    http.expectOne('/api/tipos-fecha').flush([type]);
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    types.editType(type);
    types.typeForm.en_borde = true;
    void types.saveType({ invalid: false } as NgForm);
    const updated = http.expectOne('/api/tipos-fecha/2');
    expect(updated.request.method).toBe('PATCH');
    expect(updated.request.body.en_borde).toBe(true);
    updated.flush({ ...type, en_borde: true });
    flushMicrotasks();
    http.expectOne('/api/tipos-fecha').flush([{ ...type, en_borde: true }]);
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    expect(types.dateTypes[0].en_borde).toBeTrue();
    app.state.logout();
  }));

  it('resets feature forms and reloads data when navigating between sections', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const app = fixture.componentInstance;
    login(fixture);
    app.navigate('proyectos');
    fixture.detectChanges();
    http.expectOne('/api/proyectos').flush([]);
    flushMicrotasks();
    const projects: ProjectsComponent = fixture.debugElement.query(By.directive(ProjectsComponent)).componentInstance;
    projects.projectForm.nombre = 'Sin guardar';
    app.navigate('proyectos');
    http.expectOne('/api/proyectos').flush([]);
    flushMicrotasks();
    expect(projects.projectForm.nombre).toBe('');
    projects.projectForm.nombre = 'Sin guardar';
    app.navigate('tipos');
    fixture.detectChanges();
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    app.navigate('proyectos');
    fixture.detectChanges();
    http.expectOne('/api/proyectos').flush([]);
    flushMicrotasks();
    const reopened: ProjectsComponent = fixture.debugElement.query(By.directive(ProjectsComponent)).componentInstance;
    expect(reopened).not.toBe(projects);
    expect(reopened.projectForm.nombre).toBe('');
    app.state.logout();
  }));

  it('does not expose user management to a non-administrator', fakeAsync(() => {
    localStorage.setItem('calendar_token', 'saved');
    localStorage.setItem('calendar_expiry', String(Date.now() + 3600000));
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    http.expectOne('/api/me').flush({ usuario_id: 2, activo: true, es_administrador: false });
    flushMicrotasks();
    http.expectOne('/api/get_years').flush({ years: [] });
    flushMicrotasks();
    fixture.detectChanges();
    fixture.componentInstance.state.menuOpen = true;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#settings-menu').textContent).not.toContain('Usuarios');
    fixture.componentInstance.state.logout();
  }));
});

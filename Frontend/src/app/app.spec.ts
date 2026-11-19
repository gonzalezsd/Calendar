import { TestBed, fakeAsync, flushMicrotasks, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NgForm } from '@angular/forms';
import { App } from './app';

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

  function login(app: App): void {
    app.loginName = 'admin';
    app.loginPassword = 'password123';
    void app.login({ invalid: false } as NgForm);
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
      tipados: [{ fecha: '2026-01-01', tipo_id: 1, nombre: 'Festivo', color: '#FF0000', en_borde: false }]
    });
    flushMicrotasks();
  }

  it('authenticates, displays the calendar and loads a selected year', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Iniciar sesión');
    expect(fixture.nativeElement.textContent).not.toContain('Configuración');
    login(fixture.componentInstance);
    fixture.detectChanges();
    expect(localStorage.getItem('calendar_token')).toBe('token');
    expect(fixture.nativeElement.querySelector('.year-title').textContent.trim()).toBe('2026');
    expect(fixture.nativeElement.textContent).toContain('Festivo');
    expect(fixture.nativeElement.textContent).toContain('Trabajo');
    void fixture.componentInstance.changeYear('2025');
    http.expectOne('/api/calendario/2025').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.year-title').textContent.trim()).toBe('2025');
    expect(fixture.nativeElement.textContent).not.toContain('Trabajo');
    fixture.componentInstance.logout();
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
    login(app);
    app.newYear = 2027;
    void app.createYear({ invalid: false } as NgForm);
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
    login(app);
    void app.navigate('proyectos');
    http.expectOne('/api/proyectos').flush([]);
    flushMicrotasks();
    app.projectForm.nombre = 'Proyecto A';
    void app.saveProject({ invalid: false } as NgForm);
    const created = http.expectOne('/api/proyectos');
    expect(created.request.method).toBe('POST');
    expect(created.request.body.nombre).toBe('Proyecto A');
    created.flush({ proyecto_id: 1 });
    flushMicrotasks();
    const project = { proyecto_id: 1, nombre: 'Proyecto A', descripcion: '', duracion: null, restantes: null, color: '#4f46e5' };
    http.expectOne('/api/proyectos').flush([project]);
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    app.editProject(project);
    app.projectForm.nombre = 'Proyecto B';
    void app.saveProject({ invalid: false } as NgForm);
    const updated = http.expectOne('/api/proyectos/1');
    expect(updated.request.method).toBe('PATCH');
    expect(updated.request.body.nombre).toBe('Proyecto B');
    updated.flush({ ...project, nombre: 'Proyecto B' });
    flushMicrotasks();
    http.expectOne('/api/proyectos').flush([{ ...project, nombre: 'Proyecto B' }]);
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Proyecto B');
    app.logout();
  }));

  it('creates a user and sends only changed fields when editing', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const app = fixture.componentInstance;
    login(app);
    void app.navigate('usuarios');
    http.expectOne('/api/usuarios').flush([]);
    flushMicrotasks();
    app.userForm.nombre = 'Ana';
    app.userForm.nombre_usuario = 'ana';
    app.userForm.password = 'password123';
    void app.saveUser({ invalid: false } as NgForm);
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
    app.editUser(user);
    app.userForm.nombre = 'Ana María';
    void app.saveUser({ invalid: false } as NgForm);
    const updated = http.expectOne('/api/usuarios/2');
    expect(updated.request.method).toBe('PATCH');
    expect(updated.request.body).toEqual({ nombre: 'Ana María' });
    updated.flush({ ...user, nombre: 'Ana María' });
    flushMicrotasks();
    http.expectOne('/api/me').flush({ usuario_id: 1, activo: true, es_administrador: true });
    flushMicrotasks();
    http.expectOne('/api/usuarios').flush([{ ...user, nombre: 'Ana María' }]);
    flushMicrotasks();
    expect(app.users[0].nombre).toBe('Ana María');
    app.logout();
  }));

  it('creates and edits date types through the backend', fakeAsync(() => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const app = fixture.componentInstance;
    login(app);
    void app.navigate('tipos');
    http.expectOne('/api/tipos-fecha').flush([]);
    flushMicrotasks();
    app.typeForm.nombre = 'Vacaciones';
    void app.saveType({ invalid: false } as NgForm);
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
    app.editType(type);
    app.typeForm.en_borde = true;
    void app.saveType({ invalid: false } as NgForm);
    const updated = http.expectOne('/api/tipos-fecha/2');
    expect(updated.request.method).toBe('PATCH');
    expect(updated.request.body.en_borde).toBe(true);
    updated.flush({ ...type, en_borde: true });
    flushMicrotasks();
    http.expectOne('/api/tipos-fecha').flush([{ ...type, en_borde: true }]);
    flushMicrotasks();
    http.expectOne('/api/calendario/2026').flush({ asignaciones: [], tipados: [] });
    flushMicrotasks();
    expect(app.dateTypes[0].en_borde).toBeTrue();
    app.logout();
  }));
});

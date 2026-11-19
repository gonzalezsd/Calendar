import { Component, OnInit } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';
import { CurrentUser, EditableUser, User } from '../core/models';

@Component({
  selector: 'app-users',
  imports: [FormsModule],
  templateUrl: './users.html'
})
export class UsersComponent implements OnInit {
  users: User[] = [];
  editingId: number | null = null;
  userForm: EditableUser = this.emptyUser();

  constructor(readonly state: AppState) {}

  async ngOnInit(): Promise<void> {
    await this.state.run(async () => {
      this.users = await this.state.request<User[]>('GET', '/api/usuarios');
    });
  }

  editUser(user: User): void {
    this.editingId = user.usuario_id;
    this.userForm = { ...user, password: '' };
  }

  resetForm(): void {
    this.editingId = null;
    this.userForm = this.emptyUser();
  }

  private emptyUser(): EditableUser {
    return { nombre: '', apellido1: '', apellido2: '', nombre_usuario: '', password: '', activo: true, es_administrador: false };
  }

  async saveUser(form: NgForm): Promise<void> {
    if (form.invalid) return;
    await this.state.run(async () => {
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
        this.state.message = 'No hay cambios que guardar.';
        return;
      }
      const url = this.editingId === null ? '/api/usuarios' : `/api/usuarios/${this.editingId}`;
      await this.state.request(this.editingId === null ? 'POST' : 'PATCH', url, payload);
      this.resetForm();
      this.state.user = await this.state.request<CurrentUser>('GET', '/api/me');
      if (this.state.user.es_administrador) {
        this.users = await this.state.request<User[]>('GET', '/api/usuarios');
      } else {
        this.state.view = 'calendar';
        this.users = [];
      }
      this.state.message = 'Usuario guardado.';
    });
  }
}

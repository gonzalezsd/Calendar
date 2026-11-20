import { Component, OnInit } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';
import { EditableProject, Project } from '../core/models';

@Component({
  selector: 'app-projects',
  imports: [FormsModule],
  templateUrl: './projects.html'
})
export class ProjectsComponent implements OnInit {
  projects: Project[] = [];
  editingId: number | null = null;
  projectForm: EditableProject = this.emptyProject();

  constructor(readonly state: AppState) {}

  async ngOnInit(): Promise<void> {
    const target = this.state.editTarget?.view === 'proyectos' ? this.state.editTarget.id : null;
    this.state.editTarget = null;
    await this.state.run(async () => {
      this.projects = await this.state.request<Project[]>('GET', '/api/proyectos');
      const project = this.projects.find(item => item.proyecto_id === target);
      if (project) this.editProject(project);
      else if (target !== null) this.state.error = 'El proyecto ya no está disponible.';
    });
  }

  editProject(project: Project): void {
    this.editingId = project.proyecto_id;
    this.projectForm = { ...project };
  }

  resetForm(): void {
    this.editingId = null;
    this.projectForm = this.emptyProject();
  }

  private emptyProject(): EditableProject {
    return { nombre: '', descripcion: '', duracion: null, restantes: null, color: '#4f46e5', laborable: true };
  }

  async saveProject(form: NgForm): Promise<void> {
    if (form.invalid) return;
    await this.state.run(async () => {
      const { nombre, descripcion, duracion, restantes, color, laborable } = this.projectForm;
      const url = this.editingId === null ? '/api/proyectos' : `/api/proyectos/${this.editingId}`;
      await this.state.request(this.editingId === null ? 'POST' : 'PATCH', url, { nombre, descripcion, duracion, restantes, color, laborable });
      this.resetForm();
      this.projects = await this.state.request<Project[]>('GET', '/api/proyectos');
      if (this.state.year !== null) await this.state.loadCalendar(this.state.year);
      this.state.message = 'Proyecto guardado.';
    });
  }
}

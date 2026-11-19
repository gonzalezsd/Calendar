import { Component, OnInit, ViewChild } from '@angular/core';
import { AppState } from './core/app-state';
import { View } from './core/models';
import { LoginComponent } from './login/login';
import { CalendarComponent } from './calendar/calendar';
import { UsersComponent } from './users/users';
import { ProjectsComponent } from './projects/projects';
import { DateTypesComponent } from './date-types/date-types';

@Component({
  selector: 'app-root',
  imports: [LoginComponent, CalendarComponent, UsersComponent, ProjectsComponent, DateTypesComponent],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App implements OnInit {
  @ViewChild(UsersComponent) private users?: UsersComponent;
  @ViewChild(ProjectsComponent) private projects?: ProjectsComponent;
  @ViewChild(DateTypesComponent) private dateTypes?: DateTypesComponent;

  constructor(readonly state: AppState) {}

  async ngOnInit(): Promise<void> {
    await this.state.restore();
  }

  navigate(view: View): void {
    this.state.menuOpen = false;
    if (this.state.view === view) {
      const current = view === 'usuarios' ? this.users :
        view === 'proyectos' ? this.projects : view === 'tipos' ? this.dateTypes : undefined;
      if (current) {
        current.resetForm();
        void current.ngOnInit();
      }
    }
    this.state.view = view;
  }
}

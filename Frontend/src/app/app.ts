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
  @ViewChild(CalendarComponent) calendar?: CalendarComponent;
  @ViewChild(UsersComponent) private users?: UsersComponent;
  @ViewChild(ProjectsComponent) private projects?: ProjectsComponent;
  @ViewChild(DateTypesComponent) private dateTypes?: DateTypesComponent;

  constructor(readonly state: AppState) {}

  async ngOnInit(): Promise<void> {
    await this.state.restore();
  }

  navigate(view: View): void {
    if (view !== 'calendar' && this.calendar && !this.calendar.canLeaveDay()) return;
    this.state.menuOpen = false;
    if (view === 'calendar') this.calendar?.showYear();
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

  logout(): void {
    if (this.calendar && !this.calendar.canLeaveDay()) return;
    this.state.logout();
  }

  changeYear(event: Event): void {
    const select = event.target;
    if (!(select instanceof HTMLSelectElement)) return;
    if (this.calendar && !this.calendar.canLeaveDay()) {
      select.value = String(this.state.year ?? '');
      return;
    }
    void this.state.changeYear(select.value);
  }
}

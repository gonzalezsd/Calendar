import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { AppState } from './core/app-state';
import { View } from './core/models';
import { LoginComponent } from './login/login';
import { CalendarComponent } from './calendar/calendar';
import { UsersComponent } from './users/users';
import { ProjectsComponent } from './projects/projects';
import { DateTypesComponent } from './date-types/date-types';
import { RecurringRemindersComponent } from './recurring-reminders/recurring-reminders';
import { CalendarTransferComponent } from './calendar-transfer/calendar-transfer';

@Component({
  selector: 'app-root',
  imports: [LoginComponent, CalendarComponent, UsersComponent, ProjectsComponent, DateTypesComponent, RecurringRemindersComponent, CalendarTransferComponent],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App implements OnInit {
  @ViewChild(CalendarComponent) calendar?: CalendarComponent;
  @ViewChild(UsersComponent) private users?: UsersComponent;
  @ViewChild(ProjectsComponent) private projects?: ProjectsComponent;
  @ViewChild(DateTypesComponent) private dateTypes?: DateTypesComponent;
  @ViewChild(RecurringRemindersComponent) private reminders?: RecurringRemindersComponent;
  @ViewChild(CalendarTransferComponent) private calendarTransfer?: CalendarTransferComponent;
  @ViewChild('remindersDialog') set remindersDialog(dialog: ElementRef<HTMLDialogElement> | undefined) {
    dialog?.nativeElement.showModal();
  }

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
        view === 'proyectos' ? this.projects : view === 'tipos' ? this.dateTypes :
        view === 'recordatorios' ? this.reminders : view === 'importar-exportar' ? this.calendarTransfer : undefined;
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

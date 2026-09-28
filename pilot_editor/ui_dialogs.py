"""Resizable review dialog whose action buttons keep their requested height."""
import tkinter as tk
from tkinter import ttk


class ReviewDialog(tk.Toplevel):
    def __init__(self, parent, title, text, action, action_label='Write changes'):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content = ttk.Frame(self, padding=(12, 12, 12, 8))
        content.grid(row=0, column=0, sticky='nsew')
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.body = tk.Text(content, height=1, width=1, wrap='word', font=('Segoe UI', 10), padx=10, pady=10)
        self.body.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(content, command=self.body.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.body.configure(yscrollcommand=scrollbar.set)
        self.body.insert('1.0', text)
        self.body.configure(state='disabled')
        self.footer = ttk.Frame(self, padding=(16, 8, 16, 16))
        self.footer.grid(row=1, column=0, sticky='ew')
        self.footer.columnconfigure(0, weight=1)
        self.stopped = tk.BooleanVar(self, value=False)
        self.checkbox = ttk.Checkbutton(self.footer, text='I have exited the game. RPCS3 may remain open.',
            variable=self.stopped, command=self.update_ready)
        self.checkbox.grid(row=0, column=0, columnspan=2, sticky='w')
        self.hint = ttk.Label(self.footer, text='Check the box above to enable writing. Cancel keeps your staged edits.')
        self.hint.grid(row=1, column=0, columnspan=2, sticky='w', pady=(5, 12))

        def apply():
            if self.stopped.get():
                self.destroy()
                action()

        self.write_button = ttk.Button(self.footer, text=action_label, state='disabled', command=apply, padding=(12, 5))
        self.write_button.grid(row=2, column=0, sticky='w')
        self.cancel_button = ttk.Button(self.footer, text='Cancel', command=self.destroy, padding=(12, 5))
        self.cancel_button.grid(row=2, column=1, sticky='e')
        self.bind('<Escape>', lambda _: self.destroy())
        self.update_idletasks()
        # The footer never competes with the text widget's default 24-line request.
        minimum_width = max(620, self.footer.winfo_reqwidth() + 24)
        minimum_height = self.footer.winfo_reqheight() + 150
        self.minsize(minimum_width, minimum_height)
        self.geometry(f'{max(880, minimum_width)}x{max(520, minimum_height)}')
        self.grab_set()
        self.cancel_button.focus_set()

    def update_ready(self):
        self.write_button.configure(state='normal' if self.stopped.get() else 'disabled')

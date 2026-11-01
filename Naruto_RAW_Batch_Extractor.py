# -*- coding: utf-8 -*-
"""Extrator em massa de PM0/TEX para arquivos RAW de Naruto Uzumaki Chronicles 2.

A lógica da tabela RAW segue a estrutura observada no código C# do NUC RAW Tools.
Permite exportar apenas a pasta principal ou todas as pastas internas.
Os bytes são copiados sem conversão.
"""
import os
import struct
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

APP_TITLE = "Naruto RAW Batch Extractor"

class RawFormatError(Exception):
    pass

def u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise RawFormatError(f"Campo de 32 bits fora do arquivo (offset 0x{offset:X}).")
    return struct.unpack_from('<I', data, offset)[0]

def checked_slice(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise RawFormatError(f"Bloco inválido: offset=0x{offset:X}, tamanho=0x{size:X}, arquivo=0x{len(data):X}.")
    return data[offset:offset + size]

def parse_raw(data: bytes):
    """Retorna lista de pastas, cada uma contendo os bytes e metadados dos filhos."""
    if len(data) < 12:
        raise RawFormatError('Arquivo muito pequeno para ser um RAW válido.')
    table_bytes = u32(data, 8)
    if table_bytes == 0 or table_bytes % 0x10 != 0:
        raise RawFormatError('Tabela principal inválida (campo do offset 0x08).')
    folder_count = table_bytes // 0x10
    if 12 + folder_count * 16 > len(data):
        raise RawFormatError('Tabela principal ultrapassa o tamanho do arquivo.')
    folders=[]
    for i in range(folder_count):
        size=u32(data, 4 + 16*i)
        pos=u32(data, 8 + 16*i)
        block=checked_slice(data,pos,size)
        children=[]
        # Uma pasta comum começa com contagem de arquivos e tabela de pares offset/tamanho.
        if len(block) >= 4:
            count=u32(block,0)
            table_end=4 + count*8
            aligned=(table_end + 15)//16*16
            is_container=(0 < count <= 0x9f and table_end <= len(block) and u32(block,4) >= table_end and u32(block,4) <= len(block) and aligned <= len(block))
            # O C# considera válida a tabela quando o primeiro offset coincide com a tabela alinhada.
            if is_container and u32(block,4) == aligned:
                for j in range(count):
                    child_pos=u32(block,4+8*j)
                    child_size=u32(block,8+8*j)
                    # entradas vazias/links são mantidas como None
                    if child_pos == 0 or child_size == 0:
                        children.append(None)
                    else:
                        children.append(checked_slice(block,child_pos,child_size))
        folders.append({'index':i,'data':block,'children':children})
    return folders

def extract_one(path: Path, out_dir: Path, overwrite: bool, main_only: bool = False):
    data=path.read_bytes()
    folders=parse_raw(data)
    made=[]
    # O visualizador representa os elementos como raw_<índice da pasta>_<índice do filho>.
    # Filho 0 = modelo (.pm0), filho 1 = texturas (.tex).
    # No modo principal, considera somente a primeira pasta interna (índice 0).
    folders_to_export = folders[:1] if main_only else folders
    for folder in folders_to_export:
        children=folder['children']
        if len(children) < 2:
            continue
        model=children[0]
        texture=children[1]
        if model is not None:
            target=out_dir / f'{path.stem}.pm0'
            if target.exists() and not overwrite:
                target=out_dir / f'{path.stem}_folder{folder["index"]}.pm0'
            if target.exists() and not overwrite:
                target=unique_path(target)
            target.write_bytes(model); made.append(target)
        if texture is not None:
            target=out_dir / f'{path.stem}.tex'
            if target.exists() and not overwrite:
                target=out_dir / f'{path.stem}_folder{folder["index"]}.tex'
            if target.exists() and not overwrite:
                target=unique_path(target)
            target.write_bytes(texture); made.append(target)
    if not made:
        raise RawFormatError('Não encontrei pares de entradas filho 0/1 exportáveis nas pastas deste RAW.')
    return made

def unique_path(path: Path):
    i=2
    while True:
        candidate=path.with_name(f'{path.stem}_{i}{path.suffix}')
        if not candidate.exists(): return candidate
        i+=1

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE); self.geometry('760x520'); self.minsize(660,430)
        self.files=[]; self.log_queue=queue.Queue()
        self._build(); self.after(100,self._poll_log)
    def _build(self):
        top=ttk.Frame(self,padding=12); top.pack(fill='x')
        ttk.Label(top,text='Extrator em massa de arquivos RAW',font=('Segoe UI',15,'bold')).pack(anchor='w')
        ttk.Label(top,text='Exporta a entrada 0 como .pm0 e a entrada 1 como .tex, preservando os bytes originais.').pack(anchor='w',pady=(4,10))
        row=ttk.Frame(top); row.pack(fill='x')
        ttk.Button(row,text='Adicionar arquivos .raw…',command=self.add_files).pack(side='left')
        ttk.Button(row,text='Adicionar pasta…',command=self.add_folder).pack(side='left',padx=6)
        ttk.Button(row,text='Limpar lista',command=self.clear).pack(side='left')
        self.listbox=tk.Listbox(self,height=8,selectmode=tk.EXTENDED); self.listbox.pack(fill='both',expand=True,padx=12)
        options=ttk.Frame(self,padding=(12,8)); options.pack(fill='x')
        self.recursive=tk.BooleanVar(value=True)
        ttk.Checkbutton(options,text='Incluir subpastas ao adicionar uma pasta',variable=self.recursive).pack(side='left')
        self.main_only=tk.BooleanVar(value=False)
        ttk.Checkbutton(options,text='Extrair apenas o PM0/TEX principal (ignorar folder adicionais)',variable=self.main_only).pack(side='left',padx=(14,0))
        self.overwrite=tk.BooleanVar(value=False)
        ttk.Checkbutton(options,text='Sobrescrever arquivos existentes',variable=self.overwrite).pack(side='left',padx=14)
        outrow=ttk.Frame(self,padding=(12,0)); outrow.pack(fill='x')
        ttk.Label(outrow,text='Pasta de saída:').pack(side='left')
        self.out_var=tk.StringVar(value=str(Path.cwd()/'RAW_Extraidos'))
        ttk.Entry(outrow,textvariable=self.out_var).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(outrow,text='Escolher…',command=self.choose_output).pack(side='left')
        actions=ttk.Frame(self,padding=12); actions.pack(fill='x')
        self.run_btn=ttk.Button(actions,text='Extrair tudo',command=self.start); self.run_btn.pack(side='left')
        self.progress=ttk.Progressbar(actions,mode='determinate'); self.progress.pack(side='left',fill='x',expand=True,padx=10)
        self.log=tk.Text(self,height=8,wrap='word',state='disabled'); self.log.pack(fill='both',expand=True,padx=12,pady=(0,12))
    def add_files(self):
        paths=filedialog.askopenfilenames(title='Selecione arquivos RAW',filetypes=[('Arquivos RAW','*.raw'),('Todos os arquivos','*.*')])
        self._add(paths)
    def add_folder(self):
        folder=filedialog.askdirectory(title='Selecione a pasta com arquivos RAW')
        if not folder:return
        p=Path(folder)
        found=list(p.rglob('*') if self.recursive.get() else p.glob('*'))
        self._add([str(x) for x in found if x.is_file() and x.suffix.lower()=='.raw'])
    def _add(self,paths):
        known={str(Path(x).resolve()).lower() for x in self.files}
        for p in paths:
            rp=str(Path(p).resolve())
            if rp.lower() not in known:
                self.files.append(rp); self.listbox.insert('end',rp); known.add(rp.lower())
    def clear(self): self.files=[]; self.listbox.delete(0,'end')
    def choose_output(self):
        p=filedialog.askdirectory(title='Escolha a pasta de saída')
        if p:self.out_var.set(p)
    def write_log(self,msg): self.log.configure(state='normal'); self.log.insert('end',msg+'\n'); self.log.see('end'); self.log.configure(state='disabled')
    def start(self):
        if not self.files:
            messagebox.showwarning(APP_TITLE,'Adicione um ou mais arquivos .raw primeiro.'); return
        out=Path(self.out_var.get().strip())
        if not self.out_var.get().strip():
            messagebox.showwarning(APP_TITLE,'Escolha a pasta de saída.'); return
        try: out.mkdir(parents=True,exist_ok=True)
        except Exception as e:
            messagebox.showerror(APP_TITLE,f'Não consegui criar a pasta de saída:\n{e}'); return
        self.run_btn.configure(state='disabled'); self.progress['value']=0; self.progress['maximum']=len(self.files)
        threading.Thread(target=self._worker,args=(list(self.files),out,self.overwrite.get(),self.main_only.get()),daemon=True).start()
    def _worker(self,files,out,overwrite,main_only):
        ok=0; bad=0
        for idx,p in enumerate(files,1):
            path=Path(p)
            try:
                made=extract_one(path,out,overwrite,main_only)
                self.log_queue.put(f'[OK] {path.name}: '+', '.join(x.name for x in made)); ok+=1
            except Exception as e:
                self.log_queue.put(f'[ERRO] {path.name}: {e}'); bad+=1
            self.log_queue.put(('PROGRESS',idx))
        self.log_queue.put(('DONE',ok,bad))
    def _poll_log(self):
        try:
            while True:
                item=self.log_queue.get_nowait()
                if isinstance(item,tuple) and item[0]=='PROGRESS': self.progress['value']=item[1]
                elif isinstance(item,tuple) and item[0]=='DONE':
                    self.run_btn.configure(state='normal')
                    self.write_log(f'Concluído. Sucesso: {item[1]} | Erros: {item[2]}')
                    messagebox.showinfo(APP_TITLE,f'Processamento concluído.\nRAWs com sucesso: {item[1]}\nRAWs com erro: {item[2]}')
                else:self.write_log(item)
        except queue.Empty: pass
        self.after(100,self._poll_log)

if __name__=='__main__':
    App().mainloop()

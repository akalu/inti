# 🔡 letras_grandes.py

Dibuja texto en letras **enormes** de ASCII art directo en la terminal, seguido de tres figuras geométricas pequeñas (cuadrado, triángulo y círculo) a modo de puntos suspensivos.

```
============================================================
#     #   #####   #          ###    
#     #  #     #  #         #   #   
#     #  #     #  #        #     #  
#######  #     #  #        #######  
#     #  #     #  #        #     #  
#     #  #     #  #        #     #  
#     #   #####   #######  #     #  
============================================================

  [ cuadrado ]     [ triángulo ]     [ círculo ]

    #####            #             ### 
    #####           ###           #   #
    #####          #####          #   #
    #####          #####          #   #
    #####          #####           ### 
```

---

## Requisitos

- Python 3.x
- Sin dependencias externas — solo stdlib 🎉

---

## Uso

**Pasando el texto como argumento:**
```bash
python letras_grandes.py "HOLA MUNDO"
```

**Sin argumentos (modo interactivo):**
```bash
python letras_grandes.py
# → Ingresá la palabra u oración: PYTHON
```

**Combinando varias palabras:**
```bash
python letras_grandes.py "YO AMO PYTHON"
```

---

## Caracteres soportados

| Tipo        | Caracteres                          |
|-------------|-------------------------------------|
| Letras      | A – Z (mayúsculas y minúsculas)     |
| Números     | 0 – 9                               |
| Símbolos    | `!` `?` `espacio`                   |
| Desconocido | Cualquier otro carácter muestra un símbolo genérico en lugar de romper |

---

## Figuras al pie

Al terminar de dibujar el texto, el script siempre muestra tres figuras pequeñas alineadas:

| Figura      | Descripción              |
|-------------|--------------------------|
| `#####`     | Cuadrado sólido 5×5      |
| `  #  `     | Triángulo apuntando arriba |
| ` ### `     | Círculo hueco 5×5        |

---

## Estructura del proyecto

```
letras_grandes.py   # Script principal (todo en un solo archivo)
README.md           # Este archivo
```

---

## Licencia

MIT — hacé lo que quieras con esto.

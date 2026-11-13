import { useEffect, useState } from "react";
import { Box, Dialog, DialogContent, DialogTitle, IconButton, Skeleton, Tooltip } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { api } from "../api";

interface Props {
  executionId: string;
  name: string;
  title: string;
}

/** Miniatura do screenshot de um passo; abre em grande ao clicar. */
export function Screenshot({ executionId, name, title }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let alive = true;
    api
      .artifactBlob(executionId, name)
      .then((blob) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [executionId, name]);

  if (failed) return null;
  if (!url) return <Skeleton variant="rectangular" width={64} height={128} />;

  return (
    <>
      <Tooltip title="Open screenshot">
        <Box
          component="img"
          src={url}
          alt={`Screenshot: ${title}`}
          onClick={() => setOpen(true)}
          sx={{ width: 64, height: 128, objectFit: "cover", borderRadius: 1, border: 1,
                borderColor: "divider", cursor: "zoom-in", flexShrink: 0 }}
        />
      </Tooltip>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm">
        <DialogTitle sx={{ pr: 6 }}>
          {title}
          <IconButton aria-label="close" onClick={() => setOpen(false)}
                      sx={{ position: "absolute", right: 8, top: 8 }}>
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          <Box component="img" src={url} alt={title} sx={{ display: "block", maxWidth: "100%", maxHeight: "80vh", mx: "auto" }} />
        </DialogContent>
      </Dialog>
    </>
  );
}
